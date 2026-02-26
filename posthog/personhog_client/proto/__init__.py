# ruff: noqa: E402, F401
import os
import sys

# Generated proto stubs use absolute imports from the proto package root
# (e.g. `from personhog.types.v1 import ...`). Add the generated directory
# to sys.path so these resolve correctly.
_generated_dir = os.path.join(os.path.dirname(__file__), "generated")
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)

from posthog.personhog_client.proto.generated.personhog.service.v1.service_pb2_grpc import PersonHogServiceStub
from posthog.personhog_client.proto.generated.personhog.types.v1.cohort_pb2 import (
    CheckCohortMembershipRequest,
    CohortMembership,
    CohortMembershipResponse,
)
from posthog.personhog_client.proto.generated.personhog.types.v1.common_pb2 import (
    CONSISTENCY_LEVEL_EVENTUAL,
    CONSISTENCY_LEVEL_STRONG,
    GroupIdentifier,
    GroupKey,
    ReadOptions,
    TeamDistinctId,
)
from posthog.personhog_client.proto.generated.personhog.types.v1.feature_flag_pb2 import (
    DeleteHashKeyOverridesByTeamsRequest,
    DeleteHashKeyOverridesByTeamsResponse,
    GetHashKeyOverrideContextRequest,
    GetHashKeyOverrideContextResponse,
    HashKeyOverride,
    HashKeyOverrideContext,
    UpsertHashKeyOverridesRequest,
    UpsertHashKeyOverridesResponse,
)
from posthog.personhog_client.proto.generated.personhog.types.v1.group_pb2 import (
    GetGroupRequest,
    GetGroupResponse,
    GetGroupsBatchRequest,
    GetGroupsBatchResponse,
    GetGroupsRequest,
    GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest,
    GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest,
    Group,
    GroupsResponse,
    GroupTypeMapping,
    GroupTypeMappingsBatchResponse,
    GroupTypeMappingsResponse,
    GroupWithKey,
)
from posthog.personhog_client.proto.generated.personhog.types.v1.person_pb2 import (
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest,
    GetDistinctIdsForPersonsResponse,
    GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest,
    GetPersonRequest,
    GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByDistinctIdsRequest,
    GetPersonsByUuidsRequest,
    GetPersonsRequest,
    Person,
    PersonsByDistinctIdsInTeamResponse,
    PersonsByDistinctIdsResponse,
    PersonsResponse,
)
