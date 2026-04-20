"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/types/v1/common.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/common.proto\x12\x12personhog.types.v1"H\n\x0bReadOptions\x129\n\x0bconsistency\x18\x01 \x01(\x0e2$.personhog.types.v1.ConsistencyLevel"6\n\x0eTeamDistinctId\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t"H\n\x08GroupKey\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x18\n\x10group_type_index\x18\x02 \x01(\x05\x12\x11\n\tgroup_key\x18\x03 \x01(\t">\n\x0fGroupIdentifier\x12\x18\n\x10group_type_index\x18\x01 \x01(\x05\x12\x11\n\tgroup_key\x18\x02 \x01(\t*s\n\x10ConsistencyLevel\x12!\n\x1dCONSISTENCY_LEVEL_UNSPECIFIED\x10\x00\x12\x1e\n\x1aCONSISTENCY_LEVEL_EVENTUAL\x10\x01\x12\x1c\n\x18CONSISTENCY_LEVEL_STRONG\x10\x02b\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.common_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_CONSISTENCYLEVEL"]._serialized_start = 323
    _globals["_CONSISTENCYLEVEL"]._serialized_end = 438
    _globals["_READOPTIONS"]._serialized_start = 55
    _globals["_READOPTIONS"]._serialized_end = 127
    _globals["_TEAMDISTINCTID"]._serialized_start = 129
    _globals["_TEAMDISTINCTID"]._serialized_end = 183
    _globals["_GROUPKEY"]._serialized_start = 185
    _globals["_GROUPKEY"]._serialized_end = 257
    _globals["_GROUPIDENTIFIER"]._serialized_start = 259
    _globals["_GROUPIDENTIFIER"]._serialized_end = 321
