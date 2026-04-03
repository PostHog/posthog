"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/service/v1/service.proto"
)
_sym_db = _symbol_database.Default()
from ....personhog.types.v1 import (
    cohort_pb2 as personhog_dot_types_dot_v1_dot_cohort__pb2,
    feature_flag_pb2 as personhog_dot_types_dot_v1_dot_feature__flag__pb2,
    group_pb2 as personhog_dot_types_dot_v1_dot_group__pb2,
    person_pb2 as personhog_dot_types_dot_v1_dot_person__pb2,
)

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n"personhog/service/v1/service.proto\x12\x14personhog.service.v1\x1a\x1fpersonhog/types/v1/person.proto\x1a\x1epersonhog/types/v1/group.proto\x1a\x1fpersonhog/types/v1/cohort.proto\x1a%personhog/types/v1/feature_flag.proto2\x9a\x14\n\x10PersonHogService\x12X\n\tGetPerson\x12$.personhog.types.v1.GetPersonRequest\x1a%.personhog.types.v1.GetPersonResponse\x12X\n\nGetPersons\x12%.personhog.types.v1.GetPersonsRequest\x1a#.personhog.types.v1.PersonsResponse\x12d\n\x0fGetPersonByUuid\x12*.personhog.types.v1.GetPersonByUuidRequest\x1a%.personhog.types.v1.GetPersonResponse\x12f\n\x11GetPersonsByUuids\x12,.personhog.types.v1.GetPersonsByUuidsRequest\x1a#.personhog.types.v1.PersonsResponse\x12p\n\x15GetPersonByDistinctId\x120.personhog.types.v1.GetPersonByDistinctIdRequest\x1a%.personhog.types.v1.GetPersonResponse\x12\x91\x01\n\x1dGetPersonsByDistinctIdsInTeam\x128.personhog.types.v1.GetPersonsByDistinctIdsInTeamRequest\x1a6.personhog.types.v1.PersonsByDistinctIdsInTeamResponse\x12\x7f\n\x17GetPersonsByDistinctIds\x122.personhog.types.v1.GetPersonsByDistinctIdsRequest\x1a0.personhog.types.v1.PersonsByDistinctIdsResponse\x12\x82\x01\n\x17GetDistinctIdsForPerson\x122.personhog.types.v1.GetDistinctIdsForPersonRequest\x1a3.personhog.types.v1.GetDistinctIdsForPersonResponse\x12\x85\x01\n\x18GetDistinctIdsForPersons\x123.personhog.types.v1.GetDistinctIdsForPersonsRequest\x1a4.personhog.types.v1.GetDistinctIdsForPersonsResponse\x12\x88\x01\n\x19GetHashKeyOverrideContext\x124.personhog.types.v1.GetHashKeyOverrideContextRequest\x1a5.personhog.types.v1.GetHashKeyOverrideContextResponse\x12\x7f\n\x16UpsertHashKeyOverrides\x121.personhog.types.v1.UpsertHashKeyOverridesRequest\x1a2.personhog.types.v1.UpsertHashKeyOverridesResponse\x12\x94\x01\n\x1dDeleteHashKeyOverridesByTeams\x128.personhog.types.v1.DeleteHashKeyOverridesByTeamsRequest\x1a9.personhog.types.v1.DeleteHashKeyOverridesByTeamsResponse\x12w\n\x15CheckCohortMembership\x120.personhog.types.v1.CheckCohortMembershipRequest\x1a,.personhog.types.v1.CohortMembershipResponse\x12U\n\x08GetGroup\x12#.personhog.types.v1.GetGroupRequest\x1a$.personhog.types.v1.GetGroupResponse\x12U\n\tGetGroups\x12$.personhog.types.v1.GetGroupsRequest\x1a".personhog.types.v1.GroupsResponse\x12g\n\x0eGetGroupsBatch\x12).personhog.types.v1.GetGroupsBatchRequest\x1a*.personhog.types.v1.GetGroupsBatchResponse\x12\x86\x01\n\x1cGetGroupTypeMappingsByTeamId\x127.personhog.types.v1.GetGroupTypeMappingsByTeamIdRequest\x1a-.personhog.types.v1.GroupTypeMappingsResponse\x12\x8d\x01\n\x1dGetGroupTypeMappingsByTeamIds\x128.personhog.types.v1.GetGroupTypeMappingsByTeamIdsRequest\x1a2.personhog.types.v1.GroupTypeMappingsBatchResponse\x12\x8c\x01\n\x1fGetGroupTypeMappingsByProjectId\x12:.personhog.types.v1.GetGroupTypeMappingsByProjectIdRequest\x1a-.personhog.types.v1.GroupTypeMappingsResponse\x12\x93\x01\n GetGroupTypeMappingsByProjectIds\x12;.personhog.types.v1.GetGroupTypeMappingsByProjectIdsRequest\x1a2.personhog.types.v1.GroupTypeMappingsBatchResponse\x12\x7f\n\x16UpdatePersonProperties\x121.personhog.types.v1.UpdatePersonPropertiesRequest\x1a2.personhog.types.v1.UpdatePersonPropertiesResponseb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.service.v1.service_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_PERSONHOGSERVICE"]._serialized_start = 198
    _globals["_PERSONHOGSERVICE"]._serialized_end = 2784
