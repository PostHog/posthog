"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 3, "", "personhog/types/v1/feature_flag.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n%personhog/types/v1/feature_flag.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"V\n\x0fHashKeyOverride\x12(\n\x10feature_flag_key\x18\x01 \x01(\tR\x0efeatureFlagKey\x12\x19\n\x08hash_key\x18\x02 \x01(\tR\x07hashKey"\xd6\x01\n\x16HashKeyOverrideContext\x12\x1b\n\tperson_id\x18\x01 \x01(\x03R\x08personId\x12\x1f\n\x0bdistinct_id\x18\x02 \x01(\tR\ndistinctId\x12A\n\toverrides\x18\x03 \x03(\x0b2#.personhog.types.v1.HashKeyOverrideR\toverrides\x12;\n\x1aexisting_feature_flag_keys\x18\x04 \x03(\tR\x17existingFeatureFlagKeys"\xd2\x01\n GetHashKeyOverrideContextRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12!\n\x0cdistinct_ids\x18\x02 \x03(\tR\x0bdistinctIds\x12.\n\x13check_person_exists\x18\x03 \x01(\x08R\x11checkPersonExists\x12B\n\x0cread_options\x18\x04 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"i\n!GetHashKeyOverrideContextResponse\x12D\n\x07results\x18\x01 \x03(\x0b2*.personhog.types.v1.HashKeyOverrideContextR\x07results"\xa2\x01\n\x1dUpsertHashKeyOverridesRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12!\n\x0cdistinct_ids\x18\x02 \x03(\tR\x0bdistinctIds\x12\x19\n\x08hash_key\x18\x03 \x01(\tR\x07hashKey\x12*\n\x11feature_flag_keys\x18\x04 \x03(\tR\x0ffeatureFlagKeys"G\n\x1eUpsertHashKeyOverridesResponse\x12%\n\x0einserted_count\x18\x01 \x01(\x03R\rinsertedCount"A\n$DeleteHashKeyOverridesByTeamsRequest\x12\x19\n\x08team_ids\x18\x01 \x03(\x03R\x07teamIds"L\n%DeleteHashKeyOverridesByTeamsResponse\x12#\n\rdeleted_count\x18\x01 \x01(\x03R\x0cdeletedCountb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.feature_flag_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_HASHKEYOVERRIDE"]._serialized_start = 94
    _globals["_HASHKEYOVERRIDE"]._serialized_end = 180
    _globals["_HASHKEYOVERRIDECONTEXT"]._serialized_start = 183
    _globals["_HASHKEYOVERRIDECONTEXT"]._serialized_end = 397
    _globals["_GETHASHKEYOVERRIDECONTEXTREQUEST"]._serialized_start = 400
    _globals["_GETHASHKEYOVERRIDECONTEXTREQUEST"]._serialized_end = 610
    _globals["_GETHASHKEYOVERRIDECONTEXTRESPONSE"]._serialized_start = 612
    _globals["_GETHASHKEYOVERRIDECONTEXTRESPONSE"]._serialized_end = 717
    _globals["_UPSERTHASHKEYOVERRIDESREQUEST"]._serialized_start = 720
    _globals["_UPSERTHASHKEYOVERRIDESREQUEST"]._serialized_end = 882
    _globals["_UPSERTHASHKEYOVERRIDESRESPONSE"]._serialized_start = 884
    _globals["_UPSERTHASHKEYOVERRIDESRESPONSE"]._serialized_end = 955
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSREQUEST"]._serialized_start = 957
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSREQUEST"]._serialized_end = 1022
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSRESPONSE"]._serialized_start = 1024
    _globals["_DELETEHASHKEYOVERRIDESBYTEAMSRESPONSE"]._serialized_end = 1100
