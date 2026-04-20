"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/types/v1/feature_flag.proto"
)
_sym_db = _symbol_database.Default()
from ....personhog.types.v1 import common_pb2 as personhog_dot_types_dot_v1_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n%personhog/types/v1/feature_flag.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"=\n\x0fHashKeyOverride\x12\x18\n\x10feature_flag_key\x18\x01 \x01(\t\x12\x10\n\x08hash_key\x18\x02 \x01(\t"\x9c\x01\n\x16HashKeyOverrideContext\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x126\n\toverrides\x18\x03 \x03(\x0b2#.personhog.types.v1.HashKeyOverride\x12"\n\x1aexisting_feature_flag_keys\x18\x04 \x03(\t"\x9d\x01\n GetHashKeyOverrideContextRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdistinct_ids\x18\x02 \x03(\t\x12\x1b\n\x13check_person_exists\x18\x03 \x01(\x08\x125\n\x0cread_options\x18\x04 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"`\n!GetHashKeyOverrideContextResponse\x12;\n\x07results\x18\x01 \x03(\x0b2*.personhog.types.v1.HashKeyOverrideContext"s\n\x1dUpsertHashKeyOverridesRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdistinct_ids\x18\x02 \x03(\t\x12\x10\n\x08hash_key\x18\x03 \x01(\t\x12\x19\n\x11feature_flag_keys\x18\x04 \x03(\t"8\n\x1eUpsertHashKeyOverridesResponse\x12\x16\n\x0einserted_count\x18\x01 \x01(\x03"8\n$DeleteHashKeyOverridesByTeamsRequest\x12\x10\n\x08team_ids\x18\x01 \x03(\x03">\n%DeleteHashKeyOverridesByTeamsResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03b\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.feature_flag_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_HASHKEYOVERRIDE"]._serialized_start = 94
    _globals["_HASHKEYOVERRIDE"]._serialized_end = 155
    _globals["_HASHKEYOVERRIDECONTEXT"]._serialized_start = 158
    _globals["_HASHKEYOVERRIDECONTEXT"]._serialized_end = 314
    _globals["_GETHASHKEYOVERRIDECONTEXTREQUEST"]._serialized_start = 317
    _globals["_GETHASHKEYOVERRIDECONTEXTREQUEST"]._serialized_end = 474
    _globals["_GETHASHKEYOVERRIDECONTEXTRESPONSE"]._serialized_start = 476
    _globals["_GETHASHKEYOVERRIDECONTEXTRESPONSE"]._serialized_end = 572
    _globals["_UPSERTHASHKEYOVERRIDESREQUEST"]._serialized_start = 574
    _globals["_UPSERTHASHKEYOVERRIDESREQUEST"]._serialized_end = 689
    _globals["_UPSERTHASHKEYOVERRIDESRESPONSE"]._serialized_start = 691
    _globals["_UPSERTHASHKEYOVERRIDESRESPONSE"]._serialized_end = 747
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSREQUEST"]._serialized_start = 749
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSREQUEST"]._serialized_end = 805
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSRESPONSE"]._serialized_start = 807
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSRESPONSE"]._serialized_end = 869
