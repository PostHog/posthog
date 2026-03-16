"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/types/v1/cohort.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/cohort.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"8\n\x10CohortMembership\x12\x11\n\tcohort_id\x18\x01 \x01(\x03\x12\x11\n\tis_member\x18\x02 \x01(\x08"|\n\x1cCheckCohortMembershipRequest\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12\x12\n\ncohort_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"U\n\x18CohortMembershipResponse\x129\n\x0bmemberships\x18\x01 \x03(\x0b2$.personhog.types.v1.CohortMembershipb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.cohort_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_COHORTMEMBERSHIP"]._serialized_start = 88
    _globals["_COHORTMEMBERSHIP"]._serialized_end = 144
    _globals["_CHECKCOHORTMEMBERSHIPREQUEST"]._serialized_start = 146
    _globals["_CHECKCOHORTMEMBERSHIPREQUEST"]._serialized_end = 270
    _globals["_COHORTMEMBERSHIPRESPONSE"]._serialized_start = 272
    _globals["_COHORTMEMBERSHIPRESPONSE"]._serialized_end = 357
