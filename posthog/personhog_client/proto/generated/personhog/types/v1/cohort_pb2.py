"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 3, "", "personhog/types/v1/cohort.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/cohort.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"L\n\x10CohortMembership\x12\x1b\n\tcohort_id\x18\x01 \x01(\x03R\x08cohortId\x12\x1b\n\tis_member\x18\x02 \x01(\x08R\x08isMember"\x9e\x01\n\x1cCheckCohortMembershipRequest\x12\x1b\n\tperson_id\x18\x01 \x01(\x03R\x08personId\x12\x1d\n\ncohort_ids\x18\x02 \x03(\x03R\tcohortIds\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"b\n\x18CohortMembershipResponse\x12F\n\x0bmemberships\x18\x01 \x03(\x0b2$.personhog.types.v1.CohortMembershipR\x0bmembershipsb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.cohort_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_COHORTMEMBERSHIP"]._serialized_start = 88
    _globals["_COHORTMEMBERSHIP"]._serialized_end = 164
    _globals["_CHECKCOHORTMEMBERSHIPREQUEST"]._serialized_start = 167
    _globals["_CHECKCOHORTMEMBERSHIPREQUEST"]._serialized_end = 325
    _globals["_COHORTMEMBERSHIPRESPONSE"]._serialized_start = 327
    _globals["_COHORTMEMBERSHIPRESPONSE"]._serialized_end = 425
