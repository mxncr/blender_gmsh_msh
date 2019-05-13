#####
#
# Copyright 2017-2019 Clemens Wallrath
# Copyright 2019 Thomas Portassau
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#####

# TODO:
# - export
# - all the fancy element types (only triangles by now)
# - periodic entities ($Periodic)
# - additional element and node data ($ElementData, $ElementNodeData, ...)


#
# http://wiki.blender.org/index.php/Dev:2.5/Py/Scripts/Guidelines/Addons
#
import os
import bpy
import mathutils
import shlex
from collections import OrderedDict
from bpy.props import (BoolProperty,
    FloatProperty,
    StringProperty,
    EnumProperty,
    )
from bpy_extras.io_utils import (ImportHelper,
    ExportHelper,
    unpack_list,
    unpack_face_list,
    axis_conversion,
    )

ELEMENT_TYPES = {
            1: 2, # 2-node line
            2: 3, # 3-node triangle
            3: 4, # 4-node quadrangle
            4: 4, # 4-node tetrahedron
            5: 8, # 8-node hexahedron
            6: 6, # 6-node prism
            7: 5, # 5-node pyramid
            15: 0 # 1-node point, skip imported anyway
            # ... it gets weird from here, I'll probably never implement these anyway
            }

bl_info = {
    "name": "MSH format",
    "description": "Import MSH, Import gmsh mesh.",
    "author": "Clemens Wallrath, Thomas Portassau",
    "version": (0, 3, 0),
    "blender": (2, 80, 0),
    "location": "File > Import-Export",
    "warning": "", # used for warning icon and text in addons panel
    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.5/Py/"
                "Scripts/My_Script",
    "category": "Import-Export"}

class ImportMSH(bpy.types.Operator, ImportHelper):
    """Load a gmsh MSH Mesh file"""
    bl_idname = "import_mesh.msh"
    bl_label = "Import MSH Mesh"
    filename_ext = ".msh"
    filter_glob : StringProperty(
        default="*.msh",
        options={'HIDDEN'},
    )

    axis_forward : EnumProperty(
            name="Forward",
            items=(('X', "X Forward", ""),
                   ('Y', "Y Forward", ""),
                   ('Z', "Z Forward", ""),
                   ('-X', "-X Forward", ""),
                   ('-Y', "-Y Forward", ""),
                   ('-Z', "-Z Forward", ""),
                   ),
            default='Y',
            )
    axis_up : EnumProperty(
            name="Up",
            items=(('X', "X Up", ""),
                   ('Y', "Y Up", ""),
                   ('Z', "Z Up", ""),
                   ('-X', "-X Up", ""),
                   ('-Y', "-Y Up", ""),
                   ('-Z', "-Z Up", ""),
                   ),
            default='Z',
            )

    def execute(self, context):

        keywords = self.as_keywords(ignore=('axis_forward',
            'axis_up',
            'filter_glob',
        ))
        global_matrix = axis_conversion(from_forward=self.axis_forward,
            from_up=self.axis_up,
            ).to_4x4()

        mesh, surfaces = load(self, context, **keywords)
        if not mesh:
            return {'CANCELLED'}

        scene = bpy.context.scene
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        obj.matrix_world = global_matrix

        # map surface patches to materials
        assert(len(obj.data.polygons) == len(surfaces))
        name_index_map = {}
        last_index = 0
        for i in range(len(obj.data.polygons)):
            name = surfaces[i]
            index = next((i for i,x in enumerate(obj.data.materials) if x.name.split('.')[0] == name), None) # find material even if it has a name like <name>.001
            if index == None:
                mat = bpy.data.materials.new(name)
                obj.data.materials.append(mat)
                name_index_map[name] = last_index
                index = last_index
                last_index += 1
            obj.data.polygons[i].material_index = index

        # recalculate normals
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.editmode_toggle()

        scene.update()

        return {'FINISHED'}

def menu_func_import(self, context):
    self.layout.operator(ImportMSH.bl_idname, text="gmsh MSH (v2/v4) Mesh (.msh)")


def register():
    bpy.utils.register_class(ImportMSH)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportMSH)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

def contains(faces, face): #TODO: performance is probably shit
    s = set(face)
    d = [(face, f) for f in faces if s == set(f)]
    return len(d) != 0

def skipUnknownCmd(f,c):
    print("Skiping unknown command :'%s' "%(c) )
    c = c.strip("$")
    tmp = c
    while("$End"+c not in tmp and len(tmp)>0):
        tmp = f.readline().strip("\r\n")

def load(operator, context, filepath):
    # TODO: binary format
    filepath = os.fsencode(filepath)
    f = open(filepath, 'r')
    first_line = f.readline().rstrip()
    if first_line != "$MeshFormat":
        return None
    s = list(f.readline().split())
    version_number, file_type, data_size = float(s[0]), int(s[1]), int(s[2])

    f.readline() # $EndMeshFormat
    cmd = f.readline().strip("\r\n") # $PhysicalNames ???
    physical_names = {1: {}, 2: {}, 3: {}} # dimension -> number -> name
    if cmd == "$PhysicalNames":
        number_of_names = int(f.readline().rstrip())
        for i in range(number_of_names):
            line = f.readline()
            if line.isspace():
                continue    # skip empty lines
            s = list(shlex.split(line))
            dim, num, name = int(s[0]), int(s[1]), s[2]
            #physical_names.append({"dim": dim, "num": num, "name": name})
            physical_names[dim][num] = name

        f.readline() # $EndPhysicalNames
        cmd = f.readline().strip("\r\n") # $Nodes


    if "Nodes" not in cmd: #v4 have $Entities, skiping unimplemented
        skipUnknownCmd(f,cmd)
        cmd = f.readline().strip("\r\n") # $Nodes

    number_of_nodes = 0
    nodes = {}
    if (cmd == "$ParametricNodes" or cmd == "$Nodes") and version_number < 4.0:
        number_of_nodes = int(f.readline().rstrip())
        for i in range(number_of_nodes):
            line = f.readline()
            if line.isspace():
                continue    # skip empty lines
            s = list(line.split())
            num, x, y, z = int(s[0]), float(s[1]), float(s[2]), float(s[3])
            nodes[num] = (x, y, z)

        f.readline() # $EndNodes
    elif cmd == "$Nodes":
        tmp = f.readline().rstrip().split(" ")
        number_of_nodes = int(tmp[1])
        number_of_entity_block = int(tmp[0])
        for i in range(number_of_entity_block):
            line = f.readline()
            num_nodes_in_entity = int(line.split(" ")[-1])
            for j in range(num_nodes_in_entity):
                line = f.readline()
                s = list(line.split())
                num, x, y, z = int(s[0]), float(s[1]), float(s[2]), float(s[3])
                nodes[num] = (x, y, z)

        f.readline() # $EndNodes
    else:
        skipUnknownCmd(f,cmd)



    f.readline() # $Elements

    elements = {}
    number_of_elements = 0
    if version_number < 4.0:
        number_of_elements = int(f.readline().strip())
        for i in range(number_of_elements):
            line = f.readline()
            if line.isspace():
                continue    # skip empty lines
            s = list(line.split())
            num = int(s[0])
            elem_type = int(s[1])
            num_tags = int(s[2])
            j = 3
            tags = []
            # first tag is number of physical entity, second is number of elementary geometrical entity, followed by mesh partition numbers which we ignore (if present)
            for k in range(num_tags):
                tags.append(int(s[j]))
                j += 1
            physical_entity = tags[0]
            geo_entity = tags[1]
            elem_nodes = []
            try:
                for k in range(ELEMENT_TYPES[elem_type]):
                    elem_nodes.append(int(s[j]))
                    j += 1
            except KeyError:
                print("Element %d not implemented"%(elem_type))
            elements[num] = {"type": elem_type, "physical_entity": physical_entity, "geo_entity": geo_entity, "nodes": elem_nodes}
    else:
        tmp = f.readline().rstrip().split(" ")
        number_of_entity_block = int(tmp[0])
        number_of_elements = int(tmp[1])
        for i in range(number_of_entity_block):
            line = f.readline()
            s = list(line.split())
            elem_type = int(s[2])
            number_of_elements_in_entity = int(s[3])
            for i in range(number_of_elements_in_entity):
                line = f.readline()
                if line.isspace():
                    continue    # skip empty lines
                s = list(line.split())
                num = int(s[0])
                j = 1
                elem_nodes = []
                try:
                    for k in range(ELEMENT_TYPES[elem_type]):
                        elem_nodes.append(int(s[j]))
                        j += 1
                except KeyError:
                    print("Element %d not implemented"%(elem_type))
                elements[num] = {"type": elem_type, "nodes": elem_nodes}



    verts = []
    edges = []
    faces_dict = OrderedDict()
    surface_names = []

    assert(len(nodes.items()) == number_of_nodes)
    assert(len(elements.items()) == number_of_elements)

    for i in range(number_of_nodes):
        verts.append(nodes[i+1]) # node numbers start at 1

    for i in range(number_of_elements):
        element = elements[i+1]
        if element["type"] == 1: # line
            edges.append(tuple([e - 1 for e in element["nodes"]]))
        elif element["type"] == 2 or element["type"] == 3: # triangle or quad
            face = tuple([e - 1 for e in element["nodes"]])
            key = tuple(sorted(face))
            if not faces_dict.get(key): # blender will eliminate duplicate faces anyway, but that corrups the material -> face mapping since the indices change
                faces_dict[key] = face
                if len(physical_names[2]) > 0:
                    surface_names.append(physical_names[2][element["physical_entity"]])
                else:
                    surface_names.append("no_name")
        #TODO: keep this?
        #elif element["type"] == 4: # tetrahedron
        #    for p in [[0,1,2],[1,2,3],[2,3,0],[3,0,1]]:
        #        face = (element["nodes"][p[0]] - 1, element["nodes"][p[1]] - 1, element["nodes"][p[2]] - 1)
        #        key = tuple(sorted(face))
        #        if not faces_dict.get(key): # blender will eliminate duplicate faces anyway, but that corrups the material -> face mapping since the indices change
        #            faces_dict[key] = face
        #            surface_names.append(physical_names[2][element["physical_entity"]]) # color by physical name
        #TODO: the rest

    faces = [f for f in faces_dict.keys()]

    # Assemble mesh
    msh_name = bpy.path.display_name_from_filepath(filepath)
    mesh = bpy.data.meshes.new(name=msh_name)
    mesh.from_pydata(verts,edges,faces)

    mesh.validate()
    mesh.update()

    return mesh, surface_names

if __name__ == "__main__":
    register()
