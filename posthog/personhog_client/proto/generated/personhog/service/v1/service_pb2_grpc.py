"""Client and server classes corresponding to protobuf-defined services."""

import grpc

from ....personhog.types.v1 import (
    cohort_pb2 as personhog_dot_types_dot_v1_dot_cohort__pb2,
    feature_flag_pb2 as personhog_dot_types_dot_v1_dot_feature__flag__pb2,
    group_pb2 as personhog_dot_types_dot_v1_dot_group__pb2,
    person_pb2 as personhog_dot_types_dot_v1_dot_person__pb2,
)

GRPC_GENERATED_VERSION = "1.71.2"
GRPC_VERSION = grpc.__version__
_version_not_supported = False
try:
    from grpc._utilities import first_version_is_lower

    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_GENERATED_VERSION)
except ImportError:
    _version_not_supported = True
if _version_not_supported:
    raise RuntimeError(
        f"The grpc package installed is at version {GRPC_VERSION},"
        + f" but the generated code in personhog/service/v1/service_pb2_grpc.py depends on"
        + f" grpcio>={GRPC_GENERATED_VERSION}."
        + f" Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}"
        + f" or downgrade your generated code using grpcio-tools<={GRPC_VERSION}."
    )


class PersonHogServiceStub:
    """PersonHogService is the public API exposed by the router.
    Clients call this service; the router handles backend selection and routing.
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.GetPerson = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPerson",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            _registered_method=True,
        )
        self.GetPersons = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersons",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.FromString,
            _registered_method=True,
        )
        self.GetPersonByUuid = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersonByUuid",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByUuidRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            _registered_method=True,
        )
        self.GetPersonsByUuids = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersonsByUuids",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByUuidsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.FromString,
            _registered_method=True,
        )
        self.GetPersonByDistinctId = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersonByDistinctId",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByDistinctIdRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            _registered_method=True,
        )
        self.GetPersonsByDistinctIdsInTeam = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersonsByDistinctIdsInTeam",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsInTeamRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsInTeamResponse.FromString,
            _registered_method=True,
        )
        self.GetPersonsByDistinctIds = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetPersonsByDistinctIds",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsResponse.FromString,
            _registered_method=True,
        )
        self.GetDistinctIdsForPerson = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetDistinctIdsForPerson",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonResponse.FromString,
            _registered_method=True,
        )
        self.GetDistinctIdsForPersons = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetDistinctIdsForPersons",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsResponse.FromString,
            _registered_method=True,
        )
        self.GetHashKeyOverrideContext = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetHashKeyOverrideContext",
            request_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextResponse.FromString,
            _registered_method=True,
        )
        self.UpsertHashKeyOverrides = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/UpsertHashKeyOverrides",
            request_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesResponse.FromString,
            _registered_method=True,
        )
        self.DeleteHashKeyOverridesByTeams = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/DeleteHashKeyOverridesByTeams",
            request_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsResponse.FromString,
            _registered_method=True,
        )
        self.CheckCohortMembership = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/CheckCohortMembership",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CheckCohortMembershipRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CohortMembershipResponse.FromString,
            _registered_method=True,
        )
        self.CountCohortMembers = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/CountCohortMembers",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersResponse.FromString,
            _registered_method=True,
        )
        self.DeleteCohortMember = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/DeleteCohortMember",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberResponse.FromString,
            _registered_method=True,
        )
        self.DeleteCohortMembersBulk = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/DeleteCohortMembersBulk",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkResponse.FromString,
            _registered_method=True,
        )
        self.InsertCohortMembers = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/InsertCohortMembers",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersResponse.FromString,
            _registered_method=True,
        )
        self.ListCohortMemberIds = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/ListCohortMemberIds",
            request_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsResponse.FromString,
            _registered_method=True,
        )
        self.GetGroup = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroup",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupResponse.FromString,
            _registered_method=True,
        )
        self.GetGroups = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroups",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupsResponse.FromString,
            _registered_method=True,
        )
        self.GetGroupsBatch = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroupsBatch",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchResponse.FromString,
            _registered_method=True,
        )
        self.GetGroupTypeMappingsByTeamId = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByTeamId",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.FromString,
            _registered_method=True,
        )
        self.GetGroupTypeMappingsByTeamIds = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByTeamIds",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.FromString,
            _registered_method=True,
        )
        self.GetGroupTypeMappingsByProjectId = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByProjectId",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.FromString,
            _registered_method=True,
        )
        self.GetGroupTypeMappingsByProjectIds = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByProjectIds",
            request_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.FromString,
            _registered_method=True,
        )
        self.UpdatePersonProperties = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/UpdatePersonProperties",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesResponse.FromString,
            _registered_method=True,
        )
        self.DeletePersons = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/DeletePersons",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsResponse.FromString,
            _registered_method=True,
        )
        self.DeletePersonsBatchForTeam = channel.unary_unary(
            "/personhog.service.v1.PersonHogService/DeletePersonsBatchForTeam",
            request_serializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamResponse.FromString,
            _registered_method=True,
        )


class PersonHogServiceServicer:
    """PersonHogService is the public API exposed by the router.
    Clients call this service; the router handles backend selection and routing.
    """

    def GetPerson(self, request, context):
        """Person lookups by ID"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersons(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersonByUuid(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersonsByUuids(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersonByDistinctId(self, request, context):
        """Person lookups by distinct ID"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersonsByDistinctIdsInTeam(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPersonsByDistinctIds(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetDistinctIdsForPerson(self, request, context):
        """Distinct ID operations"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetDistinctIdsForPersons(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetHashKeyOverrideContext(self, request, context):
        """Feature flag hash key override support"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def UpsertHashKeyOverrides(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def DeleteHashKeyOverridesByTeams(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def CheckCohortMembership(self, request, context):
        """Cohort membership"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def CountCohortMembers(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def DeleteCohortMember(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def DeleteCohortMembersBulk(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def InsertCohortMembers(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def ListCohortMemberIds(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroup(self, request, context):
        """Groups"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroups(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroupsBatch(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroupTypeMappingsByTeamId(self, request, context):
        """Group type mappings"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroupTypeMappingsByTeamIds(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroupTypeMappingsByProjectId(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetGroupTypeMappingsByProjectIds(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def UpdatePersonProperties(self, request, context):
        """Person property updates (routed to leader)"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def DeletePersons(self, request, context):
        """Person deletes
        WARNING: This is a write operation on person data. It should route to the leader
        once personhog-leader supports deletes. Currently routed through the replica
        (which uses the primary Postgres pool) as a temporary measure.
        TODO: Migrate routing to leader before personhog-leader goes live.
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def DeletePersonsBatchForTeam(self, request, context):
        """WARNING: Same routing caveat as DeletePersons above."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_PersonHogServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "GetPerson": grpc.unary_unary_rpc_method_handler(
            servicer.GetPerson,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.SerializeToString,
        ),
        "GetPersons": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersons,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.SerializeToString,
        ),
        "GetPersonByUuid": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersonByUuid,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByUuidRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.SerializeToString,
        ),
        "GetPersonsByUuids": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersonsByUuids,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByUuidsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.SerializeToString,
        ),
        "GetPersonByDistinctId": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersonByDistinctId,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByDistinctIdRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.SerializeToString,
        ),
        "GetPersonsByDistinctIdsInTeam": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersonsByDistinctIdsInTeam,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsInTeamRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsInTeamResponse.SerializeToString,
        ),
        "GetPersonsByDistinctIds": grpc.unary_unary_rpc_method_handler(
            servicer.GetPersonsByDistinctIds,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsResponse.SerializeToString,
        ),
        "GetDistinctIdsForPerson": grpc.unary_unary_rpc_method_handler(
            servicer.GetDistinctIdsForPerson,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonResponse.SerializeToString,
        ),
        "GetDistinctIdsForPersons": grpc.unary_unary_rpc_method_handler(
            servicer.GetDistinctIdsForPersons,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsResponse.SerializeToString,
        ),
        "GetHashKeyOverrideContext": grpc.unary_unary_rpc_method_handler(
            servicer.GetHashKeyOverrideContext,
            request_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextResponse.SerializeToString,
        ),
        "UpsertHashKeyOverrides": grpc.unary_unary_rpc_method_handler(
            servicer.UpsertHashKeyOverrides,
            request_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesResponse.SerializeToString,
        ),
        "DeleteHashKeyOverridesByTeams": grpc.unary_unary_rpc_method_handler(
            servicer.DeleteHashKeyOverridesByTeams,
            request_deserializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsResponse.SerializeToString,
        ),
        "CheckCohortMembership": grpc.unary_unary_rpc_method_handler(
            servicer.CheckCohortMembership,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CheckCohortMembershipRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CohortMembershipResponse.SerializeToString,
        ),
        "CountCohortMembers": grpc.unary_unary_rpc_method_handler(
            servicer.CountCohortMembers,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersResponse.SerializeToString,
        ),
        "DeleteCohortMember": grpc.unary_unary_rpc_method_handler(
            servicer.DeleteCohortMember,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberResponse.SerializeToString,
        ),
        "DeleteCohortMembersBulk": grpc.unary_unary_rpc_method_handler(
            servicer.DeleteCohortMembersBulk,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkResponse.SerializeToString,
        ),
        "InsertCohortMembers": grpc.unary_unary_rpc_method_handler(
            servicer.InsertCohortMembers,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersResponse.SerializeToString,
        ),
        "ListCohortMemberIds": grpc.unary_unary_rpc_method_handler(
            servicer.ListCohortMemberIds,
            request_deserializer=personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsResponse.SerializeToString,
        ),
        "GetGroup": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroup,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupResponse.SerializeToString,
        ),
        "GetGroups": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroups,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupsResponse.SerializeToString,
        ),
        "GetGroupsBatch": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroupsBatch,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchResponse.SerializeToString,
        ),
        "GetGroupTypeMappingsByTeamId": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroupTypeMappingsByTeamId,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.SerializeToString,
        ),
        "GetGroupTypeMappingsByTeamIds": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroupTypeMappingsByTeamIds,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.SerializeToString,
        ),
        "GetGroupTypeMappingsByProjectId": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroupTypeMappingsByProjectId,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.SerializeToString,
        ),
        "GetGroupTypeMappingsByProjectIds": grpc.unary_unary_rpc_method_handler(
            servicer.GetGroupTypeMappingsByProjectIds,
            request_deserializer=personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.SerializeToString,
        ),
        "UpdatePersonProperties": grpc.unary_unary_rpc_method_handler(
            servicer.UpdatePersonProperties,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesResponse.SerializeToString,
        ),
        "DeletePersons": grpc.unary_unary_rpc_method_handler(
            servicer.DeletePersons,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsResponse.SerializeToString,
        ),
        "DeletePersonsBatchForTeam": grpc.unary_unary_rpc_method_handler(
            servicer.DeletePersonsBatchForTeam,
            request_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler("personhog.service.v1.PersonHogService", rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers("personhog.service.v1.PersonHogService", rpc_method_handlers)


class PersonHogService:
    """PersonHogService is the public API exposed by the router.
    Clients call this service; the router handles backend selection and routing.
    """

    @staticmethod
    def GetPerson(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPerson",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersons(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersons",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersonByUuid(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersonByUuid",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByUuidRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersonsByUuids(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersonsByUuids",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByUuidsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.PersonsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersonByDistinctId(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersonByDistinctId",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonByDistinctIdRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersonsByDistinctIdsInTeam(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersonsByDistinctIdsInTeam",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsInTeamRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsInTeamResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetPersonsByDistinctIds(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetPersonsByDistinctIds",
            personhog_dot_types_dot_v1_dot_person__pb2.GetPersonsByDistinctIdsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.PersonsByDistinctIdsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetDistinctIdsForPerson(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetDistinctIdsForPerson",
            personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetDistinctIdsForPersons(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetDistinctIdsForPersons",
            personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.GetDistinctIdsForPersonsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetHashKeyOverrideContext(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetHashKeyOverrideContext",
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.GetHashKeyOverrideContextResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def UpsertHashKeyOverrides(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/UpsertHashKeyOverrides",
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.UpsertHashKeyOverridesResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def DeleteHashKeyOverridesByTeams(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/DeleteHashKeyOverridesByTeams",
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_feature__flag__pb2.DeleteHashKeyOverridesByTeamsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def CheckCohortMembership(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/CheckCohortMembership",
            personhog_dot_types_dot_v1_dot_cohort__pb2.CheckCohortMembershipRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.CohortMembershipResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def CountCohortMembers(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/CountCohortMembers",
            personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.CountCohortMembersResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def DeleteCohortMember(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/DeleteCohortMember",
            personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMemberResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def DeleteCohortMembersBulk(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/DeleteCohortMembersBulk",
            personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.DeleteCohortMembersBulkResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def InsertCohortMembers(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/InsertCohortMembers",
            personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.InsertCohortMembersResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def ListCohortMemberIds(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/ListCohortMemberIds",
            personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_cohort__pb2.ListCohortMemberIdsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroup(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroup",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroups(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroups",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GroupsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroupsBatch(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroupsBatch",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupsBatchResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroupTypeMappingsByTeamId(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByTeamId",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroupTypeMappingsByTeamIds(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByTeamIds",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByTeamIdsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroupTypeMappingsByProjectId(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByProjectId",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def GetGroupTypeMappingsByProjectIds(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/GetGroupTypeMappingsByProjectIds",
            personhog_dot_types_dot_v1_dot_group__pb2.GetGroupTypeMappingsByProjectIdsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_group__pb2.GroupTypeMappingsBatchResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def UpdatePersonProperties(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/UpdatePersonProperties",
            personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.UpdatePersonPropertiesResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def DeletePersons(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/DeletePersons",
            personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

    @staticmethod
    def DeletePersonsBatchForTeam(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/personhog.service.v1.PersonHogService/DeletePersonsBatchForTeam",
            personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamRequest.SerializeToString,
            personhog_dot_types_dot_v1_dot_person__pb2.DeletePersonsBatchForTeamResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )
