from __future__ import annotations

import threading
from typing import Optional

from django.conf import settings

import grpc
import structlog

from posthog.personhog_client.proto import (
    CheckCohortMembershipRequest,
    CohortMembershipResponse,
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest,
    GetDistinctIdsForPersonsResponse,
    GetGroupRequest,
    GetGroupResponse,
    GetGroupsBatchRequest,
    GetGroupsBatchResponse,
    GetGroupsRequest,
    GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest,
    GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest,
    GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest,
    GetPersonRequest,
    GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByUuidsRequest,
    GetPersonsRequest,
    GroupsResponse,
    GroupTypeMappingsBatchResponse,
    GroupTypeMappingsResponse,
    PersonHogServiceStub,
    PersonsByDistinctIdsInTeamResponse,
    PersonsResponse,
)

logger = structlog.get_logger(__name__)


class PersonHogClient:
    def __init__(self, addr: str, timeout_ms: int = 5000):
        self._channel = grpc.insecure_channel(addr)
        self._stub = PersonHogServiceStub(self._channel)
        self._timeout = timeout_ms / 1000.0

    def close(self) -> None:
        self._channel.close()

    # -- Person lookups --

    def get_person(self, request: GetPersonRequest) -> GetPersonResponse:
        return self._stub.GetPerson(request, timeout=self._timeout)

    def get_persons(self, request: GetPersonsRequest) -> PersonsResponse:
        return self._stub.GetPersons(request, timeout=self._timeout)

    def get_person_by_uuid(self, request: GetPersonByUuidRequest) -> GetPersonResponse:
        return self._stub.GetPersonByUuid(request, timeout=self._timeout)

    def get_persons_by_uuids(self, request: GetPersonsByUuidsRequest) -> PersonsResponse:
        return self._stub.GetPersonsByUuids(request, timeout=self._timeout)

    # -- Person lookups by distinct ID --

    def get_person_by_distinct_id(self, request: GetPersonByDistinctIdRequest) -> GetPersonResponse:
        return self._stub.GetPersonByDistinctId(request, timeout=self._timeout)

    def get_persons_by_distinct_ids_in_team(
        self, request: GetPersonsByDistinctIdsInTeamRequest
    ) -> PersonsByDistinctIdsInTeamResponse:
        return self._stub.GetPersonsByDistinctIdsInTeam(request, timeout=self._timeout)

    # -- Distinct ID operations --

    def get_distinct_ids_for_person(self, request: GetDistinctIdsForPersonRequest) -> GetDistinctIdsForPersonResponse:
        return self._stub.GetDistinctIdsForPerson(request, timeout=self._timeout)

    def get_distinct_ids_for_persons(
        self, request: GetDistinctIdsForPersonsRequest
    ) -> GetDistinctIdsForPersonsResponse:
        return self._stub.GetDistinctIdsForPersons(request, timeout=self._timeout)

    # -- Cohort membership --

    def check_cohort_membership(self, request: CheckCohortMembershipRequest) -> CohortMembershipResponse:
        return self._stub.CheckCohortMembership(request, timeout=self._timeout)

    # -- Groups --

    def get_group(self, request: GetGroupRequest) -> GetGroupResponse:
        return self._stub.GetGroup(request, timeout=self._timeout)

    def get_groups(self, request: GetGroupsRequest) -> GroupsResponse:
        return self._stub.GetGroups(request, timeout=self._timeout)

    def get_groups_batch(self, request: GetGroupsBatchRequest) -> GetGroupsBatchResponse:
        return self._stub.GetGroupsBatch(request, timeout=self._timeout)

    # -- Group type mappings --

    def get_group_type_mappings_by_team_id(
        self, request: GetGroupTypeMappingsByTeamIdRequest
    ) -> GroupTypeMappingsResponse:
        return self._stub.GetGroupTypeMappingsByTeamId(request, timeout=self._timeout)

    def get_group_type_mappings_by_team_ids(
        self, request: GetGroupTypeMappingsByTeamIdsRequest
    ) -> GroupTypeMappingsBatchResponse:
        return self._stub.GetGroupTypeMappingsByTeamIds(request, timeout=self._timeout)

    def get_group_type_mappings_by_project_id(
        self, request: GetGroupTypeMappingsByProjectIdRequest
    ) -> GroupTypeMappingsResponse:
        return self._stub.GetGroupTypeMappingsByProjectId(request, timeout=self._timeout)

    def get_group_type_mappings_by_project_ids(
        self, request: GetGroupTypeMappingsByProjectIdsRequest
    ) -> GroupTypeMappingsBatchResponse:
        return self._stub.GetGroupTypeMappingsByProjectIds(request, timeout=self._timeout)


_client: Optional[PersonHogClient] = None
_lock = threading.Lock()


def get_personhog_client() -> Optional[PersonHogClient]:
    global _client
    addr = getattr(settings, "PERSONHOG_ADDR", "")
    if not addr:
        return None

    if _client is None:
        with _lock:
            if _client is None:
                timeout_ms = getattr(settings, "PERSONHOG_TIMEOUT_MS", 5000)
                _client = PersonHogClient(addr=addr, timeout_ms=timeout_ms)
                logger.info("personhog_client_initialized", addr=addr, timeout_ms=timeout_ms)

    return _client
