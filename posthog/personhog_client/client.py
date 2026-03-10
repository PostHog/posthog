from __future__ import annotations

import threading
from typing import Optional

from django.conf import settings

import grpc
import structlog

from posthog.personhog_client.interceptor import ClientNameInterceptor, MetricsInterceptor
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
    def __init__(
        self,
        addr: str,
        client_name: str = "posthog-django",
        timeout_ms: int = 5000,
        keepalive_time_ms: int = 30_000,
        keepalive_timeout_ms: int = 5_000,
        keepalive_without_calls: bool = True,
        max_reconnect_backoff_ms: int = 5_000,
        initial_reconnect_backoff_ms: int = 1_000,
        max_send_message_length: int = 4 * 1024 * 1024,
        max_recv_message_length: int = 128 * 1024 * 1024,
    ):
        options = [
            ("grpc.keepalive_time_ms", keepalive_time_ms),
            ("grpc.keepalive_timeout_ms", keepalive_timeout_ms),
            ("grpc.keepalive_permit_without_calls", int(keepalive_without_calls)),
            ("grpc.http2.max_pings_without_data", 0),
            ("grpc.max_reconnect_backoff_ms", max_reconnect_backoff_ms),
            ("grpc.initial_reconnect_backoff_ms", initial_reconnect_backoff_ms),
            ("grpc.max_send_message_length", max_send_message_length),
            ("grpc.max_receive_message_length", max_recv_message_length),
            ("grpc.enable_retries", 1),
        ]
        channel = grpc.insecure_channel(addr, options=options)
        self._channel = grpc.intercept_channel(
            channel, ClientNameInterceptor(client_name), MetricsInterceptor(client_name)
        )
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

    if _client is None:
        with _lock:
            if _client is None:
                addr = getattr(settings, "PERSONHOG_ADDR", "")
                if not addr:
                    return None

                timeout_ms = getattr(settings, "PERSONHOG_TIMEOUT_MS", 5000)
                client_name = getattr(settings, "OTEL_SERVICE_NAME", None) or "posthog-django"
                _client = PersonHogClient(
                    addr=addr,
                    client_name=client_name,
                    timeout_ms=timeout_ms,
                    keepalive_time_ms=getattr(settings, "PERSONHOG_KEEPALIVE_TIME_MS", 30_000),
                    keepalive_timeout_ms=getattr(settings, "PERSONHOG_KEEPALIVE_TIMEOUT_MS", 5_000),
                    keepalive_without_calls=getattr(settings, "PERSONHOG_KEEPALIVE_WITHOUT_CALLS", True),
                    max_reconnect_backoff_ms=getattr(settings, "PERSONHOG_MAX_RECONNECT_BACKOFF_MS", 5_000),
                    initial_reconnect_backoff_ms=getattr(settings, "PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS", 1_000),
                    max_send_message_length=getattr(settings, "PERSONHOG_MAX_SEND_MESSAGE_LENGTH", 4 * 1024 * 1024),
                    max_recv_message_length=getattr(settings, "PERSONHOG_MAX_RECV_MESSAGE_LENGTH", 128 * 1024 * 1024),
                )
                logger.info("personhog_client_initialized", addr=addr, timeout_ms=timeout_ms)

    return _client
