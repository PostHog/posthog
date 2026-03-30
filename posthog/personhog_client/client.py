from __future__ import annotations

import time
import threading
from typing import Optional

from django.conf import settings

import grpc
import structlog
from prometheus_client import Counter, Enum, Histogram

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

# -- Channel-level metrics --

PERSONHOG_DJANGO_CHANNEL_STATE = Enum(
    "personhog_django_grpc_channel_state",
    "Current gRPC channel connectivity state",
    labelnames=["client_name"],
    states=["IDLE", "CONNECTING", "READY", "TRANSIENT_FAILURE", "SHUTDOWN"],
)

PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL = Counter(
    "personhog_django_grpc_channel_state_transitions_total",
    "gRPC channel connectivity state transitions",
    labelnames=["from_state", "to_state", "client_name"],
)

PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS = Histogram(
    "personhog_django_grpc_connection_establishment_seconds",
    "Time to establish a gRPC connection (CONNECTING to READY)",
    labelnames=["client_name"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


class _ChannelStateMonitor:
    """Subscribes to gRPC channel connectivity changes and emits Prometheus metrics."""

    def __init__(self, channel: grpc.Channel, client_name: str) -> None:
        self._channel = channel
        self._client_name = client_name
        self._previous_state: grpc.ChannelConnectivity | None = None
        self._connecting_since: float | None = None
        channel.subscribe(self._on_state_change)

    def _on_state_change(self, new_state: grpc.ChannelConnectivity) -> None:
        prev = self._previous_state
        self._previous_state = new_state

        PERSONHOG_DJANGO_CHANNEL_STATE.labels(client_name=self._client_name).state(new_state.name)
        PERSONHOG_DJANGO_CHANNEL_STATE_TRANSITIONS_TOTAL.labels(
            from_state=prev.name if prev else "NONE",
            to_state=new_state.name,
            client_name=self._client_name,
        ).inc()

        if new_state == grpc.ChannelConnectivity.CONNECTING:
            self._connecting_since = time.monotonic()
        elif new_state == grpc.ChannelConnectivity.READY and self._connecting_since is not None:
            PERSONHOG_DJANGO_CONNECTION_ESTABLISHMENT_SECONDS.labels(
                client_name=self._client_name,
            ).observe(time.monotonic() - self._connecting_since)
            self._connecting_since = None
        elif new_state in (
            grpc.ChannelConnectivity.TRANSIENT_FAILURE,
            grpc.ChannelConnectivity.SHUTDOWN,
            grpc.ChannelConnectivity.IDLE,
        ):
            self._connecting_since = None

    def close(self) -> None:
        try:
            self._channel.unsubscribe(self._on_state_change)
        except Exception:
            pass


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
        client_idle_timeout_ms: int = 0,
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
            # Prevent the channel from transitioning to IDLE between requests.
            ("grpc.client_idle_timeout_ms", client_idle_timeout_ms),
        ]
        channel = grpc.insecure_channel(addr, options=options)
        self._channel = grpc.intercept_channel(
            channel, ClientNameInterceptor(client_name), MetricsInterceptor(client_name)
        )
        self._state_monitor = _ChannelStateMonitor(channel, client_name)
        self._stub = PersonHogServiceStub(self._channel)
        self._timeout = timeout_ms / 1000.0

    def close(self) -> None:
        self._state_monitor.close()
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
                    client_idle_timeout_ms=getattr(settings, "PERSONHOG_CLIENT_IDLE_TIMEOUT_MS", 0),
                )
                logger.info("personhog_client_initialized", addr=addr, timeout_ms=timeout_ms)

    return _client
