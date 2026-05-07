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
from ....personhog.types.v1 import common_pb2 as personhog_dot_types_dot_v1_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/cohort.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"8\n\x10CohortMembership\x12\x11\n\tcohort_id\x18\x01 \x01(\x03\x12\x11\n\tis_member\x18\x02 \x01(\x08"|\n\x1cCheckCohortMembershipRequest\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12\x12\n\ncohort_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"U\n\x18CohortMembershipResponse\x129\n\x0bmemberships\x18\x01 \x03(\x0b2$.personhog.types.v1.CohortMembership"f\n\x19CountCohortMembersRequest\x12\x12\n\ncohort_ids\x18\x01 \x03(\x03\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"+\n\x1aCountCohortMembersResponse\x12\r\n\x05count\x18\x01 \x01(\x03"A\n\x19DeleteCohortMemberRequest\x12\x11\n\tcohort_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03"-\n\x1aDeleteCohortMemberResponse\x12\x0f\n\x07deleted\x18\x01 \x01(\x08"H\n\x1eDeleteCohortMembersBulkRequest\x12\x12\n\ncohort_ids\x18\x01 \x03(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x05"8\n\x1fDeleteCohortMembersBulkResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"e\n\x1aInsertCohortMembersRequest\x12\x11\n\tcohort_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x12\x14\n\x07version\x18\x03 \x01(\x05H\x00\x88\x01\x01B\n\n\x08_version"5\n\x1bInsertCohortMembersResponse\x12\x16\n\x0einserted_count\x18\x01 \x01(\x03"\x85\x01\n\x1aListCohortMemberIdsRequest\x12\x11\n\tcohort_id\x18\x01 \x01(\x03\x12\x0e\n\x06cursor\x18\x02 \x01(\x03\x12\r\n\x05limit\x18\x03 \x01(\x05\x125\n\x0cread_options\x18\x04 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"F\n\x1bListCohortMemberIdsResponse\x12\x12\n\nperson_ids\x18\x01 \x03(\x03\x12\x13\n\x0bnext_cursor\x18\x02 \x01(\x03b\x06proto3'
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
    _globals["_COUNTCOHORTMEMBERSREQUEST"]._serialized_start = 359
    _globals["_COUNTCOHORTMEMBERSREQUEST"]._serialized_end = 461
    _globals["_COUNTCOHORTMEMBERSRESPONSE"]._serialized_start = 463
    _globals["_COUNTCOHORTMEMBERSRESPONSE"]._serialized_end = 506
    _globals["_DELETECOHORTMEMBERREQUEST"]._serialized_start = 508
    _globals["_DELETECOHORTMEMBERREQUEST"]._serialized_end = 573
    _globals["_DELETECOHORTMEMBERRESPONSE"]._serialized_start = 575
    _globals["_DELETECOHORTMEMBERRESPONSE"]._serialized_end = 620
    _globals["_DELETECOHORTMEMBERSBULKREQUEST"]._serialized_start = 622
    _globals["_DELETECOHORTMEMBERSBULKREQUEST"]._serialized_end = 694
    _globals["_DELETECOHORTMEMBERSBULKRESPONSE"]._serialized_start = 696
    _globals["_DELETECOHORTMEMBERSBULKRESPONSE"]._serialized_end = 752
    _globals["_INSERTCOHORTMEMBERSREQUEST"]._serialized_start = 754
    _globals["_INSERTCOHORTMEMBERSREQUEST"]._serialized_end = 855
    _globals["_INSERTCOHORTMEMBERSRESPONSE"]._serialized_start = 857
    _globals["_INSERTCOHORTMEMBERSRESPONSE"]._serialized_end = 910
    _globals["_LISTCOHORTMEMBERIDSREQUEST"]._serialized_start = 913
    _globals["_LISTCOHORTMEMBERIDSREQUEST"]._serialized_end = 1046
    _globals["_LISTCOHORTMEMBERIDSRESPONSE"]._serialized_start = 1048
    _globals["_LISTCOHORTMEMBERIDSRESPONSE"]._serialized_end = 1118
