"""Client and server classes corresponding to protobuf-defined services."""

import grpc

from ....personhog.leader.v1 import leader_pb2 as personhog_dot_leader_dot_v1_dot_leader__pb2
from ....personhog.types.v1 import person_pb2 as personhog_dot_types_dot_v1_dot_person__pb2

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
        + f" but the generated code in personhog/leader/v1/leader_pb2_grpc.py depends on"
        + f" grpcio>={GRPC_GENERATED_VERSION}."
        + f" Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}"
        + f" or downgrade your generated code using grpcio-tools<={GRPC_VERSION}."
    )


class PersonHogLeaderStub:
    """PersonHogLeader is the internal write API exposed by leader pods.
    The router calls this service after hashing (team_id, person_id) to a
    partition and resolving the owning pod via the coordination routing table.
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.UpdatePersonProperties = channel.unary_unary(
            "/personhog.leader.v1.PersonHogLeader/UpdatePersonProperties",
            request_serializer=personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesRequest.SerializeToString,
            response_deserializer=personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesResponse.FromString,
            _registered_method=True,
        )
        self.GetPerson = channel.unary_unary(
            "/personhog.leader.v1.PersonHogLeader/GetPerson",
            request_serializer=personhog_dot_leader_dot_v1_dot_leader__pb2.LeaderGetPersonRequest.SerializeToString,
            response_deserializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.FromString,
            _registered_method=True,
        )


class PersonHogLeaderServicer:
    """PersonHogLeader is the internal write API exposed by leader pods.
    The router calls this service after hashing (team_id, person_id) to a
    partition and resolving the owning pod via the coordination routing table.
    """

    def UpdatePersonProperties(self, request, context):
        """Apply property updates to a person. Merges $set, $set_once, and $unset
        diffs into the cached person state.
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")

    def GetPerson(self, request, context):
        """Strong consistency read: returns the latest person state from the leader's cache."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_PersonHogLeaderServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "UpdatePersonProperties": grpc.unary_unary_rpc_method_handler(
            servicer.UpdatePersonProperties,
            request_deserializer=personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesRequest.FromString,
            response_serializer=personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesResponse.SerializeToString,
        ),
        "GetPerson": grpc.unary_unary_rpc_method_handler(
            servicer.GetPerson,
            request_deserializer=personhog_dot_leader_dot_v1_dot_leader__pb2.LeaderGetPersonRequest.FromString,
            response_serializer=personhog_dot_types_dot_v1_dot_person__pb2.GetPersonResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler("personhog.leader.v1.PersonHogLeader", rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers("personhog.leader.v1.PersonHogLeader", rpc_method_handlers)


class PersonHogLeader:
    """PersonHogLeader is the internal write API exposed by leader pods.
    The router calls this service after hashing (team_id, person_id) to a
    partition and resolving the owning pod via the coordination routing table.
    """

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
            "/personhog.leader.v1.PersonHogLeader/UpdatePersonProperties",
            personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesRequest.SerializeToString,
            personhog_dot_leader_dot_v1_dot_leader__pb2.UpdatePersonPropertiesResponse.FromString,
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
            "/personhog.leader.v1.PersonHogLeader/GetPerson",
            personhog_dot_leader_dot_v1_dot_leader__pb2.LeaderGetPersonRequest.SerializeToString,
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
