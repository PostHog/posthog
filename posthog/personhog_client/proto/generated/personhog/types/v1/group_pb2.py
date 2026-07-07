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
    b'\n\x1epersonhog/types/v1/group.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\xd7\x01\n\x05Group\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0f\n\x07team_id\x18\x02 \x01(\x03\x12\x18\n\x10group_type_index\x18\x03 \x01(\x05\x12\x11\n\tgroup_key\x18\x04 \x01(\t\x12\x18\n\x10group_properties\x18\x05 \x01(\x0c\x12\x12\n\ncreated_at\x18\x06 \x01(\x03\x12"\n\x1aproperties_last_updated_at\x18\x07 \x01(\x0c\x12!\n\x19properties_last_operation\x18\x08 \x01(\x0c\x12\x0f\n\x07version\x18\t \x01(\x03"\xdd\x02\n\x10GroupTypeMapping\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0f\n\x07team_id\x18\x02 \x01(\x03\x12\x12\n\nproject_id\x18\x03 \x01(\x03\x12\x12\n\ngroup_type\x18\x04 \x01(\t\x12\x18\n\x10group_type_index\x18\x05 \x01(\x05\x12\x1a\n\rname_singular\x18\x06 \x01(\tH\x00\x88\x01\x01\x12\x18\n\x0bname_plural\x18\x07 \x01(\tH\x01\x88\x01\x01\x12\x1c\n\x0fdefault_columns\x18\x08 \x01(\x0cH\x02\x88\x01\x01\x12 \n\x13detail_dashboard_id\x18\t \x01(\x03H\x03\x88\x01\x01\x12\x17\n\ncreated_at\x18\n \x01(\x03H\x04\x88\x01\x01B\x10\n\x0e_name_singularB\x0e\n\x0c_name_pluralB\x12\n\x10_default_columnsB\x16\n\x14_detail_dashboard_idB\r\n\x0b_created_at"r\n\x0cGroupWithKey\x12)\n\x03key\x18\x01 \x01(\x0b2\x1c.personhog.types.v1.GroupKey\x12-\n\x05group\x18\x02 \x01(\x0b2\x19.personhog.types.v1.GroupH\x00\x88\x01\x01B\x08\n\x06_group"]\n\x16GroupTypeMappingsByKey\x12\x0b\n\x03key\x18\x01 \x01(\x03\x126\n\x08mappings\x18\x02 \x03(\x0b2$.personhog.types.v1.GroupTypeMapping"\xe1\x01\n\x11ListGroupsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x1a\n\x12group_key_contains\x18\x03 \x01(\t\x12\x0e\n\x06search\x18\x04 \x01(\t\x12\x1c\n\x14cursor_created_at_ms\x18\x05 \x01(\x03\x12\x11\n\tcursor_id\x18\x06 \x01(\x03\x12\r\n\x05limit\x18\x07 \x01(\x05\x125\n\x0cread_options\x18\x08 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"Q\n\x12ListGroupsResponse\x12)\n\x06groups\x18\x01 \x03(\x0b2\x19.personhog.types.v1.Group\x12\x10\n\x08has_more\x18\x02 \x01(\x08"\x86\x01\n\x0fGetGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x125\n\x0cread_options\x18\x04 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"K\n\x10GetGroupResponse\x12-\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.GroupH\x00\x88\x01\x01B\x08\n\x06_group"\x9a\x01\n\x10GetGroupsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12>\n\x11group_identifiers\x18\x02 \x03(\x0b2#.personhog.types.v1.GroupIdentifier\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"x\n\x0eGroupsResponse\x12)\n\x06groups\x18\x01 \x03(\x0b2\x19.personhog.types.v1.Group\x12;\n\x0emissing_groups\x18\x02 \x03(\x0b2#.personhog.types.v1.GroupIdentifier"z\n\x15GetGroupsBatchRequest\x12*\n\x04keys\x18\x01 \x03(\x0b2\x1c.personhog.types.v1.GroupKey\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"K\n\x16GetGroupsBatchResponse\x121\n\x07results\x18\x01 \x03(\x0b2 .personhog.types.v1.GroupWithKey"m\n#GetGroupTypeMappingsByTeamIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"o\n$GetGroupTypeMappingsByTeamIdsRequest\x12\x10\n\x08team_ids\x18\x01 \x03(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"s\n&GetGroupTypeMappingsByProjectIdRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"u\n\'GetGroupTypeMappingsByProjectIdsRequest\x12\x13\n\x0bproject_ids\x18\x01 \x03(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"S\n\x19GroupTypeMappingsResponse\x126\n\x08mappings\x18\x01 \x03(\x0b2$.personhog.types.v1.GroupTypeMapping"]\n\x1eGroupTypeMappingsBatchResponse\x12;\n\x07results\x18\x01 \x03(\x0b2*.personhog.types.v1.GroupTypeMappingsByKey"V\n\x1dCountGroupTypeMappingsRequest\x125\n\x0cread_options\x18\x01 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"7\n\x15GroupTypeMappingCount\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\r\n\x05count\x18\x02 \x01(\x03"[\n\x1eCountGroupTypeMappingsResponse\x129\n\x06counts\x18\x01 \x03(\x0b2).personhog.types.v1.GroupTypeMappingCount"\x94\x01\n\x12CreateGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x12\x18\n\x10group_properties\x18\x04 \x01(\x0c\x12\x17\n\ncreated_at\x18\x05 \x01(\x03H\x00\x88\x01\x01B\r\n\x0b_created_at"?\n\x13CreateGroupResponse\x12(\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.Group"\xd1\x02\n\x12UpdateGroupRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t\x12\x13\n\x0bupdate_mask\x18\x04 \x03(\t\x12\x1d\n\x10group_properties\x18\x05 \x01(\x0cH\x00\x88\x01\x01\x12\'\n\x1aproperties_last_updated_at\x18\x06 \x01(\x0cH\x01\x88\x01\x01\x12&\n\x19properties_last_operation\x18\x07 \x01(\x0cH\x02\x88\x01\x01\x12\x17\n\ncreated_at\x18\x08 \x01(\x03H\x03\x88\x01\x01B\x13\n\x11_group_propertiesB\x1d\n\x1b_properties_last_updated_atB\x1c\n\x1a_properties_last_operationB\r\n\x0b_created_at"P\n\x13UpdateGroupResponse\x12(\n\x05group\x18\x01 \x01(\x0b2\x19.personhog.types.v1.Group\x12\x0f\n\x07updated\x18\x02 \x01(\x08"F\n\x1fDeleteGroupsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03"9\n DeleteGroupsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"\xce\x02\n\x1dUpdateGroupTypeMappingRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x13\n\x0bupdate_mask\x18\x03 \x03(\t\x12\x1a\n\rname_singular\x18\x04 \x01(\tH\x00\x88\x01\x01\x12\x18\n\x0bname_plural\x18\x05 \x01(\tH\x01\x88\x01\x01\x12 \n\x13detail_dashboard_id\x18\x06 \x01(\x03H\x02\x88\x01\x01\x12\x1c\n\x0fdefault_columns\x18\x07 \x01(\x0cH\x03\x88\x01\x01\x12\x17\n\ncreated_at\x18\x08 \x01(\x03H\x04\x88\x01\x01B\x10\n\x0e_name_singularB\x0e\n\x0c_name_pluralB\x16\n\x14_detail_dashboard_idB\x12\n\x10_default_columnsB\r\n\x0b_created_at"W\n\x1eUpdateGroupTypeMappingResponse\x125\n\x07mapping\x18\x01 \x01(\x0b2$.personhog.types.v1.GroupTypeMapping"\x87\x01\n\'GetGroupTypeMappingByDashboardIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdashboard_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"r\n(GetGroupTypeMappingByDashboardIdResponse\x12:\n\x07mapping\x18\x01 \x01(\x0b2$.personhog.types.v1.GroupTypeMappingH\x00\x88\x01\x01B\n\n\x08_mapping"M\n\x1dDeleteGroupTypeMappingRequest\x12\x12\n\nproject_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05"1\n\x1eDeleteGroupTypeMappingResponse\x12\x0f\n\x07deleted\x18\x01 \x01(\x08"Q\n*DeleteGroupTypeMappingsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03"D\n+DeleteGroupTypeMappingsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03b\x06proto3'
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
    _globals["_LISTGROUPSREQUEST"]._serialized_start = 869
    _globals["_LISTGROUPSREQUEST"]._serialized_end = 1094
    _globals["_LISTGROUPSRESPONSE"]._serialized_start = 1096
    _globals["_LISTGROUPSRESPONSE"]._serialized_end = 1177
    _globals["_GETGROUPREQUEST"]._serialized_start = 1180
    _globals["_GETGROUPREQUEST"]._serialized_end = 1314
    _globals["_GETGROUPRESPONSE"]._serialized_start = 1316
    _globals["_GETGROUPRESPONSE"]._serialized_end = 1391
    _globals["_GETGROUPSREQUEST"]._serialized_start = 1394
    _globals["_GETGROUPSREQUEST"]._serialized_end = 1548
    _globals["_GROUPSRESPONSE"]._serialized_start = 1550
    _globals["_GROUPSRESPONSE"]._serialized_end = 1670
    _globals["_GETGROUPSBATCHREQUEST"]._serialized_start = 1672
    _globals["_GETGROUPSBATCHREQUEST"]._serialized_end = 1794
    _globals["_GETGROUPSBATCHRESPONSE"]._serialized_start = 1796
    _globals["_GETGROUPSBATCHRESPONSE"]._serialized_end = 1871
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDREQUEST"]._serialized_start = 1873
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDREQUEST"]._serialized_end = 1982
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDSREQUEST"]._serialized_start = 1984
    _globals["_GETGROUPTYPEMAPPINGSBYTEAMIDSREQUEST"]._serialized_end = 2095
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDREQUEST"]._serialized_start = 2097
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDREQUEST"]._serialized_end = 2212
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDSREQUEST"]._serialized_start = 2214
    _globals["_GETGROUPTYPEMAPPINGSBYPROJECTIDSREQUEST"]._serialized_end = 2331
    _globals["_GROUPTYPEMAPPINGSRESPONSE"]._serialized_start = 2333
    _globals["_GROUPTYPEMAPPINGSRESPONSE"]._serialized_end = 2416
    _globals["_GROUPTYPEMAPPINGSBATCHRESPONSE"]._serialized_start = 2418
    _globals["_GROUPTYPEMAPPINGSBATCHRESPONSE"]._serialized_end = 2511
    _globals["_COUNTGROUPTYPEMAPPINGSREQUEST"]._serialized_start = 2513
    _globals["_COUNTGROUPTYPEMAPPINGSREQUEST"]._serialized_end = 2599
    _globals["_GROUPTYPEMAPPINGCOUNT"]._serialized_start = 2601
    _globals["_GROUPTYPEMAPPINGCOUNT"]._serialized_end = 2656
    _globals["_COUNTGROUPTYPEMAPPINGSRESPONSE"]._serialized_start = 2658
    _globals["_COUNTGROUPTYPEMAPPINGSRESPONSE"]._serialized_end = 2749
    _globals["_CREATEGROUPREQUEST"]._serialized_start = 2752
    _globals["_CREATEGROUPREQUEST"]._serialized_end = 2900
    _globals["_CREATEGROUPRESPONSE"]._serialized_start = 2902
    _globals["_CREATEGROUPRESPONSE"]._serialized_end = 2965
    _globals["_UPDATEGROUPREQUEST"]._serialized_start = 2968
    _globals["_UPDATEGROUPREQUEST"]._serialized_end = 3305
    _globals["_UPDATEGROUPRESPONSE"]._serialized_start = 3307
    _globals["_UPDATEGROUPRESPONSE"]._serialized_end = 3387
    _globals["_DELETEGROUPSBATCHFORTEAMREQUEST"]._serialized_start = 3389
    _globals["_DELETEGROUPSBATCHFORTEAMREQUEST"]._serialized_end = 3459
    _globals["_DELETEGROUPSBATCHFORTEAMRESPONSE"]._serialized_start = 3461
    _globals["_DELETEGROUPSBATCHFORTEAMRESPONSE"]._serialized_end = 3518
    _globals["_UPDATEGROUPTYPEMAPPINGREQUEST"]._serialized_start = 3521
    _globals["_UPDATEGROUPTYPEMAPPINGREQUEST"]._serialized_end = 3855
    _globals["_UPDATEGROUPTYPEMAPPINGRESPONSE"]._serialized_start = 3857
    _globals["_UPDATEGROUPTYPEMAPPINGRESPONSE"]._serialized_end = 3944
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDREQUEST"]._serialized_start = 3947
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDREQUEST"]._serialized_end = 4082
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDRESPONSE"]._serialized_start = 4084
    _globals["_GETGROUPTYPEMAPPINGBYDASHBOARDIDRESPONSE"]._serialized_end = 4198
    _globals["_DELETEGROUPTYPEMAPPINGREQUEST"]._serialized_start = 4200
    _globals["_DELETEGROUPTYPEMAPPINGREQUEST"]._serialized_end = 4277
    _globals["_DELETEGROUPTYPEMAPPINGRESPONSE"]._serialized_start = 4279
    _globals["_DELETEGROUPTYPEMAPPINGRESPONSE"]._serialized_end = 4328
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMREQUEST"]._serialized_start = 4330
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMREQUEST"]._serialized_end = 4411
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMRESPONSE"]._serialized_start = 4413
    _globals["_DELETEGROUPTYPEMAPPINGSBATCHFORTEAMRESPONSE"]._serialized_end = 4481
