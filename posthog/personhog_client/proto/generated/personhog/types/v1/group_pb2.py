"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/types/v1/group.proto"
)
_sym_db = _symbol_database.Default()
from ....personhog.types.v1 import common_pb2 as personhog_dot_types_dot_v1_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1epersonhog/types/v1/group.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\xd7\x01\n\x05Group\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0f\n\x07team_id\x18\x02 \x01(\x03\x12\x18\n\x10group_type_index\x18\x03 \x01(\x05\x12\x11\n\tgroup_key\x18\x04 \x01(\t\x12\x18\n\x10group_properties\x18\x05 \x01(\x0c\x12\x12\n\ncreated_at\x18\x06 \x01(\x03\x12"\n\x1aproperties_last_updated_at\x18\x07 \x01(\x0c\x12!\n\x19properties_last_operation\x18\x08 \x01(\x0c\x12\x0f\n\x07version\x18\t \x01(\x03"\xdd\x02\n\x10GroupTypeMapping\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0f\n\x07team_id\x18\x02 \x01(\x03\x12\x12\n\nproject_id\x18\x03 \x01(\x03\x12\x12\n\ngroup_type\x18\x04 \x01(\t\x12\x18\n\x10group_type_index\x18\x05 \x01(\x05\x12\x1a\n\rname_singular\x18\x06 \x01(\tH\x00\x88\x01\x01\x12\x18\n\x0bname_plural\x18\x07 \x01(\tH\x01\x88\x01\x01\x12\x1c\n\x0fdefault_columns\x18\x08 \x01(\x0cH\x02\x88\x01\x01\x12 \n\x13detail_dashboard_id\x18\t \x01(\x03H\x03\x88\x01\x01\x12\x17\n\ncreated_at\x18\n \x01(\x03H\x04\x88\x01\x01B\x10\n\x0e_name_singularB\x0e\n\x0c_name_pluralB\x12\n\x10_default_columnsB\x16\n\x14_detail_dashboard_idB\r\n\x0b_created_at"r\n\x0cGroupWithKey\x12)\n\x03key\x18\x01 \x01(\x0b2\x1c.personhog.types.v1.GroupKey\x12-\n\x05group\x18\x02 \x01(\x0b2\x19.personhog.types.v1.GroupH\x00\x88\x01\x01B\x08\n\x06_group"]\n\x16GroupTypeMappingsByKey\x12\x0b\n\x03key\x18\x01 \x01(\x03\x126\n\x08mappings\x18\x02 \x03(\x0b2$.personhog.types.v1.GroupTypeMapping"\x86\x01\n\x0fGetGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x125\n\x0cread_options\x18\x04 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"K\n\x10GetGroupResponse\x12-\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.GroupH\x00\x88\x01\x01B\x08\n\x06_group"\x9a\x01\n\x10GetGroupsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12>\n\x11group_identifiers\x18\x02 \x03(\x0b2#.personhog.types.v1.GroupIdentifier\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"x\n\x0eGroupsResponse\x12)\n\x06groups\x18\x01 \x03(\x0b2\x19.personhog.types.v1.Group\x12;\n\x0emissing_groups\x18\x02 \x03(\x0b2#.personhog.types.v1.GroupIdentifier"z\n\x15GetGroupsBatchRequest\x12*\n\x04keys\x18\x01 \x03(\x0b2\x1c.personhog.types.v1.GroupKey\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"K\n\x16GetGroupsBatchResponse\x121\n\x07results\x18\x01 \x03(\x0b2 .personhog.types.v1.GroupWithKey"m\n#GetGroupTypeMappingsByTeamIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"o\n$GetGroupTypeMappingsByTeamIdsRequest\x12\x10\n\x08team_ids\x18\x01 \x03(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"s\n&GetGroupTypeMappingsByProjectIdRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"u\n\'GetGroupTypeMappingsByProjectIdsRequest\x12\x13\n\x0bproject_ids\x18\x01 \x03(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"S\n\x19GroupTypeMappingsResponse\x126\n\x08mappings\x18\x01 \x03(\x0b2$.personhog.types.v1.GroupTypeMapping"]\n\x1eGroupTypeMappingsBatchResponse\x12;\n\x07results\x18\x01 \x03(\x0b2*.personhog.types.v1.GroupTypeMappingsByKey"\x94\x01\n\x12CreateGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x12\x18\n\x10group_properties\x18\x04 \x01(\x0c\x12\x17\n\ncreated_at\x18\x05 \x01(\x03H\x00\x88\x01\x01B\r\n\x0b_created_at"?\n\x13CreateGroupResponse\x12(\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.Group"\xd1\x02\n\x12UpdateGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x12\x13\n\x0bupdate_mask\x18\x04 \x03(\t\x12\x1d\n\x10group_properties\x18\x05 \x01(\x0cH\x00\x88\x01\x01\x12\'\n\x1aproperties_last_updated_at\x18\x06 \x01(\x0cH\x01\x88\x01\x01\x12&\n\x19properties_last_operation\x18\x07 \x01(\x0cH\x02\x88\x01\x01\x12\x17\n\ncreated_at\x18\x08 \x01(\x03H\x03\x88\x01\x01B\x13\n\x11_group_propertiesB\x1d\n\x1b_properties_last_updated_atB\x1c\n\x1a_properties_last_operationB\r\n\x0b_created_at"P\n\x13UpdateGroupResponse\x12(\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.Group\x12\x0f\n\x07updated\x18\x02 \x01(\x08"F\n\x1fDeleteGroupsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03"9\n DeleteGroupsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"\xa6\x02\n\x1dUpdateGroupTypeMappingRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x13\n\x0bupdate_mask\x18\x03 \x03(\t\x12\x1a\n\rname_singular\x18\x04 \x01(\tH\x00\x88\x01\x01\x12\x18\n\x0bname_plural\x18\x05 \x01(\tH\x01\x88\x01\x01\x12 \n\x13detail_dashboard_id\x18\x06 \x01(\x03H\x02\x88\x01\x01\x12\x1c\n\x0fdefault_columns\x18\x07 \x01(\x0cH\x03\x88\x01\x01B\x10\n\x0e_name_singularB\x0e\n\x0c_name_pluralB\x16\n\x14_detail_dashboard_idB\x12\n\x10_default_columns"W\n\x1eUpdateGroupTypeMappingResponse\x125\n\x07mapping\x18\x01 \x01(\x0b2$.personhog.types.v1.GroupTypeMapping"\x87\x01\n\'GetGroupTypeMappingByDashboardIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdashboard_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"r\n(GetGroupTypeMappingByDashboardIdResponse\x12:\n\x07mapping\x18\x01 \x01(\x0b2$.personhog.types.v1.GroupTypeMappingH\x00\x88\x01\x01B\n\n\x08_mapping"M\n\x1dDeleteGroupTypeMappingRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05"1\n\x1eDeleteGroupTypeMappingResponse\x12\x0f\n\x07deleted\x18\x01 \x01(\x08"Q\n*DeleteGroupTypeMappingsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03"D\n+DeleteGroupTypeMappingsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03b\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.group_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_GROUP"]._serialized_start = 88
    _globals["_GROUP"]._serialized_end = 303
    _globals["_GROUPTYPEMAPPING"]._serialized_start = 306
    _globals["_GROUPTYPEMAPPING"]._serialized_end = 655
    _globals["_GROUPWITHKEY"]._serialized_start = 657
    _globals["_GROUPWITHKEY"]._serialized_end = 771
    _globals["_GROUPTYPEMAPPINGSBYKEY"]._serialized_start = 773
    _globals["_GROUPTYPEMAPPINGSBYKEY"]._serialized_end = 866
    _globals["_GETGROUPREQUEST"]._serialized_start = 869
    _globals["_GETGROUPREQUEST"]._serialized_end = 1003
    _globals["_GETGROUPRESPONSE"]._serialized_start = 1005
    _globals["_GETGROUPRESPONSE"]._serialized_end = 1080
    _globals["_GETGROUPSREQUEST"]._serialized_start = 1083
    _globals["_GETGROUPSREQUEST"]._serialized_end = 1237
    _globals["_GROUPSRESPONSE"]._serialized_start = 1239
    _globals["_GROUPSRESPONSE"]._serialized_end = 1359
    _globals["_GETGROUPSBATCHREQUEST"]._serialized_start = 1361
    _globals["_GETGROUPSBATCHREQUEST"]._serialized_end = 1483
    _globals["_GETGROUPSBATCHRESPONSE"]._serialized_start = 1485
    _globals["_GETGROUPSBATCHRESPONSE"]._serialized_end = 1560
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDREQUEST"]._serialized_start = 1562
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDREQUEST"]._serialized_end = 1671
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDSREQUEST"]._serialized_start = 1673
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDSREQUEST"]._serialized_end = 1784
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDREQUEST"]._serialized_start = 1786
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDREQUEST"]._serialized_end = 1901
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDSREQUEST"]._serialized_start = 1903
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDSREQUEST"]._serialized_end = 2020
    _globals["_GROUPTYPEMAPPINGSRESPONSE"]._serialized_start = 2022
    _globals["_GROUPTYPEMAPPINGSRESPONSE"]._serialized_end = 2105
    _globals["_GROUPTYPEMAPPINGSBATCHRESPONSE"]._serialized_start = 2107
    _globals["_GROUPTYPEMAPPINGSBATCHRESPONSE"]._serialized_end = 2200
    _globals["_CREATEGROUPREQUEST"]._serialized_start = 2203
    _globals["_CREATEGROUPREQUEST"]._serialized_end = 2351
    _globals["_CREATEGROUPRESPONSE"]._serialized_start = 2353
    _globals["_CREATEGROUPRESPONSE"]._serialized_end = 2416
    _globals["_UPDATEGROUPREQUEST"]._serialized_start = 2419
    _globals["_UPDATEGROUPREQUEST"]._serialized_end = 2756
    _globals["_UPDATEGROUPRESPONSE"]._serialized_start = 2758
    _globals["_UPDATEGROUPRESPONSE"]._serialized_end = 2838
    _globals["_DELETEGROUPSBATCHFORTEAMREQUEST"]._serialized_start = 2840
    _globals["_DELETEGROUPSBATCHFORTEAMREQUEST"]._serialized_end = 2910
    _globals["_DELETEGROUPSBATCHFORTEAMRESPONSE"]._serialized_start = 2912
    _globals["_DELETEGROUPSBATCHFORTEAMRESPONSE"]._serialized_end = 2969
    _globals["_UPDATEGROUPTYPEMAPPINGREQUEST"]._serialized_start = 2972
    _globals["_UPDATEGROUPTYPEMAPPINGREQUEST"]._serialized_end = 3266
    _globals["_UPDATEGROUPTYPEMAPPINGRESPONSE"]._serialized_start = 3268
    _globals["_UPDATEGROUPTYPEMAPPINGRESPONSE"]._serialized_end = 3355
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDREQUEST"]._serialized_start = 3358
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDREQUEST"]._serialized_end = 3493
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDRESPONSE"]._serialized_start = 3495
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDRESPONSE"]._serialized_end = 3609
    _globals["_DELETEGROUPTYPEMAPPINGREQUEST"]._serialized_start = 3611
    _globals["_DELETEGROUPTYPEMAPPINGREQUEST"]._serialized_end = 3688
    _globals["_DELETEGROUPTYPEMAPPINGRESPONSE"]._serialized_start = 3690
    _globals["_DELETEGROUPTYPEMAPPINGRESPONSE"]._serialized_end = 3739
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMREQUEST"]._serialized_start = 3741
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMREQUEST"]._serialized_end = 3822
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMRESPONSE"]._serialized_start = 3824
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMRESPONSE"]._serialized_end = 3892
