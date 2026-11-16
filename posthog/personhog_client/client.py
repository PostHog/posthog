from __future__ import annotations

import time
import threading
from collections.abc import Callable
from typing import Optional, TypeVar

from django.conf import settings

import grpc
import structlog
from prometheus_client import Counter, Enum, Histogram

from posthog.personhog_client.interceptor import (
    ClientNameInterceptor,
    ConsistencyHeaderInterceptor,
    MetricsInterceptor,
    RetryInterceptor,
)
from posthog.personhog_client.proto import (
    AckPersonTombstonesRequest,
    AckPersonTombstonesResponse,
    CheckCohortMembershipRequest,
    CohortMembershipResponse,
    CountCohortMembersRequest,
    CountCohortMembersResponse,
    CountGroupTypeMappingsRequest,
    CountGroupTypeMappingsResponse,
    CreateGroupRequest,
    CreateGroupResponse,
    DeleteCohortMemberRequest,
    DeleteCohortMemberResponse,
    DeleteCohortMembersBulkRequest,
    DeleteCohortMembersBulkResponse,
    DeleteGroupsBatchForTeamRequest,
    DeleteGroupsBatchForTeamResponse,
    DeleteGroupTypeMappingRequest,
    DeleteGroupTypeMappingResponse,
    DeleteGroupTypeMappingsBatchForTeamRequest,
    DeleteGroupTypeMappingsBatchForTeamResponse,
    DeleteHashKeyOverridesByTeamsRequest,
    DeleteHashKeyOverridesByTeamsResponse,
    DeletePersonsBatchForTeamRequest,
    DeletePersonsBatchForTeamResponse,
    DeletePersonsRequest,
    DeletePersonsResponse,
    DeleteTombstonedPersonsRequest,
    DeleteTombstonedPersonsResponse,
    EnsurePersonVersionFloorsRequest,
    EnsurePersonVersionFloorsResponse,
    GetDistinctIdRowsRequest,
    GetDistinctIdRowsResponse,
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest,
    GetDistinctIdsForPersonsResponse,
    GetGroupRequest,
    GetGroupResponse,
    GetGroupsBatchRequest,
    GetGroupsBatchResponse,
    GetGroupsRequest,
    GetGroupTypeMappingByDashboardIdRequest,
    GetGroupTypeMappingByDashboardIdResponse,
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
    GetPersonTombstonesRequest,
    GetPersonTombstonesResponse,
    GroupsResponse,
    GroupTypeMappingsBatchResponse,
    GroupTypeMappingsResponse,
    InsertCohortMembersRequest,
    InsertCohortMembersResponse,
    LifecycleDeletePersonsRequest,
    LifecycleDeletePersonsResponse,
    ListCohortMemberIdsRequest,
    ListCohortMemberIdsResponse,
    ListGroupsRequest,
    ListGroupsResponse,
    ListPersonsForTeamRequest,
    ListPersonsForTeamResponse,
    ListPersonTombstoneQueueRequest,
    ListPersonTombstoneQueueResponse,
    PersonHogLifecycleStub,
    PersonHogServiceStub,
    PersonsByDistinctIdsInTeamResponse,
    PersonsResponse,
    RaisePersonVersionFloorsRequest,
    RaisePersonVersionFloorsResponse,
    RaisePersonVersionRequest,
    RaisePersonVersionResponse,
    RestorePersonsRequest,
    RestorePersonsResponse,
    SetPersonDistinctIdVersionFloorRequest,
    SetPersonDistinctIdVersionFloorResponse,
    SetPersonVersionFloorRequest,
    SetPersonVersionFloorResponse,
    SplitPersonRequest,
    SplitPersonResponse,
    UpdateGroupRequest,
    UpdateGroupResponse,
    UpdateGroupTypeMappingRequest,
    UpdateGroupTypeMappingResponse,
    WriteDistinctIdsRequest,
    WriteDistinctIdsResponse,
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


class PersonHogLifecycleUnavailable(RuntimeError):
    """The client has no lifecycle channel because PERSONHOG_LIFECYCLE_ADDR is not set."""


class PersonHogLifecycleClient:
    """The identity server's sagas, reached as ``client.lifecycle`` over their own channel.

    The facade and the lifecycle service both have a DeletePersons, with opposite consistency: the
    facade writes the replica's database directly, a saga fences the person's leader first. Keeping
    the sagas behind their own namespace makes the destination visible at every call site.
    """

    def __init__(self, stub: PersonHogLifecycleStub | None, timeout: float) -> None:
        self._stub = stub
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return self._stub is not None

    def delete_persons(
        self, request: LifecycleDeletePersonsRequest, timeout: float | None = None
    ) -> LifecycleDeletePersonsResponse:
        """Run the delete saga for up to 250 person ids of one team.

        The call returns once the saga is complete: the persons are tombstoned in Postgres and their
        leaders have produced the death documents. Retry a transient failure with the SAME op_id and
        the byte-identical person_ids list; the retry attaches to the existing operation and returns
        its recorded outcome. A FAILED_PRECONDITION whose ``semantic_refusal_reason`` is
        ``op_id_reused`` means the op_id belongs to a different request and must not be retried.
        """
        if self._stub is None:
            raise PersonHogLifecycleUnavailable("personhog lifecycle client not configured (PERSONHOG_LIFECYCLE_ADDR)")
        return self._stub.DeletePersons(request, timeout=timeout or self._timeout)


class PersonHogClient:
    def __init__(
        self,
        addr: str,
        client_name: str = "posthog-django",
        timeout_ms: int = 5000,
        lifecycle_addr: str = "",
        lifecycle_timeout_ms: int = 45_000,
        keepalive_time_ms: int = 30_000,
        keepalive_timeout_ms: int = 5_000,
        keepalive_without_calls: bool = True,
        max_reconnect_backoff_ms: int = 5_000,
        initial_reconnect_backoff_ms: int = 1_000,
        max_send_message_length: int = 4 * 1024 * 1024,
        max_recv_message_length: int = 128 * 1024 * 1024,
        client_idle_timeout_ms: int = 0,
        max_retries: int = 1,
        initial_backoff_ms: int = 50,
        max_backoff_ms: int = 1000,
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
        retry_interceptor = RetryInterceptor(
            client_name,
            max_retries=max_retries,
            initial_backoff_ms=initial_backoff_ms,
            max_backoff_ms=max_backoff_ms,
        )
        channel = grpc.insecure_channel(addr, options=options)
        self._channel = grpc.intercept_channel(
            channel,
            ClientNameInterceptor(client_name),
            ConsistencyHeaderInterceptor(),
            retry_interceptor,
            MetricsInterceptor(client_name),
        )
        self._state_monitor = _ChannelStateMonitor(channel, client_name)
        self._stub = PersonHogServiceStub(self._channel)
        self._timeout = timeout_ms / 1000.0

        # The identity server sits behind a different router than the facade. No consistency header:
        # lifecycle requests have no read_options. Retries are safe: every request carries an op_id.
        self._lifecycle_channel: grpc.Channel | None = None
        self._lifecycle_state_monitor: _ChannelStateMonitor | None = None
        lifecycle_stub: PersonHogLifecycleStub | None = None
        self._leader_stub: PersonHogServiceStub | None = None
        if lifecycle_addr:
            lifecycle_channel = grpc.insecure_channel(lifecycle_addr, options=options)
            self._lifecycle_channel = grpc.intercept_channel(
                lifecycle_channel,
                ClientNameInterceptor(client_name),
                retry_interceptor,
                MetricsInterceptor(client_name),
            )
            # The channel-state gauge is keyed by client_name alone; two channels under one name would fight over it.
            self._lifecycle_state_monitor = _ChannelStateMonitor(lifecycle_channel, f"{client_name}-lifecycle")
            lifecycle_stub = PersonHogLifecycleStub(self._lifecycle_channel)
            # The same router reaches the leader, which the facade router cannot.
            self._leader_stub = PersonHogServiceStub(self._lifecycle_channel)
        self.lifecycle = PersonHogLifecycleClient(lifecycle_stub, lifecycle_timeout_ms / 1000.0)

    def close(self) -> None:
        self._state_monitor.close()
        self._channel.close()
        if self._lifecycle_state_monitor is not None:
            self._lifecycle_state_monitor.close()
        if self._lifecycle_channel is not None:
            self._lifecycle_channel.close()

    # -- Person deletes --

    def delete_persons(self, request: DeletePersonsRequest, timeout: float | None = None) -> DeletePersonsResponse:
        return self._stub.DeletePersons(request, timeout=timeout or self._timeout)

    def delete_persons_batch_for_team(
        self, request: DeletePersonsBatchForTeamRequest, timeout: float | None = None
    ) -> DeletePersonsBatchForTeamResponse:
        return self._stub.DeletePersonsBatchForTeam(request, timeout=timeout or self._timeout)

    def delete_tombstoned_persons(
        self, request: DeleteTombstonedPersonsRequest, timeout: float | None = None
    ) -> DeleteTombstonedPersonsResponse:
        return self._stub.DeleteTombstonedPersons(request, timeout=timeout or self._timeout)

    def get_person_tombstones(
        self, request: GetPersonTombstonesRequest, timeout: float | None = None
    ) -> GetPersonTombstonesResponse:
        return self._stub.GetPersonTombstones(request, timeout=timeout or self._timeout)

    def ack_person_tombstones(
        self, request: AckPersonTombstonesRequest, timeout: float | None = None
    ) -> AckPersonTombstonesResponse:
        return self._stub.AckPersonTombstones(request, timeout=timeout or self._timeout)

    def list_person_tombstone_queue(
        self, request: ListPersonTombstoneQueueRequest, timeout: float | None = None
    ) -> ListPersonTombstoneQueueResponse:
        return self._stub.ListPersonTombstoneQueue(request, timeout=timeout or self._timeout)

    # -- Person split --

    def split_person(self, request: SplitPersonRequest, timeout: float | None = None) -> SplitPersonResponse:
        return self._stub.SplitPerson(request, timeout=timeout or self._timeout)

    # -- Undelete repair --

    def set_person_distinct_id_version_floor(
        self, request: SetPersonDistinctIdVersionFloorRequest, timeout: float | None = None
    ) -> SetPersonDistinctIdVersionFloorResponse:
        return self._stub.SetPersonDistinctIdVersionFloor(request, timeout=timeout or self._timeout)

    def set_person_version_floor(
        self, request: SetPersonVersionFloorRequest, timeout: float | None = None
    ) -> SetPersonVersionFloorResponse:
        return self._stub.SetPersonVersionFloor(request, timeout=timeout or self._timeout)

    # -- Version floors --

    def ensure_person_version_floors(
        self, request: EnsurePersonVersionFloorsRequest, timeout: float | None = None
    ) -> EnsurePersonVersionFloorsResponse:
        return self._stub.EnsurePersonVersionFloors(request, timeout=timeout or self._timeout)

    def get_distinct_id_rows(
        self, request: GetDistinctIdRowsRequest, timeout: float | None = None
    ) -> GetDistinctIdRowsResponse:
        return self._stub.GetDistinctIdRows(request, timeout=timeout or self._timeout)

    def list_persons_for_team(
        self, request: ListPersonsForTeamRequest, timeout: float | None = None
    ) -> ListPersonsForTeamResponse:
        return self._stub.ListPersonsForTeam(request, timeout=timeout or self._timeout)

    def raise_person_version_floors(
        self, request: RaisePersonVersionFloorsRequest, timeout: float | None = None
    ) -> RaisePersonVersionFloorsResponse:
        return self._stub.RaisePersonVersionFloors(request, timeout=timeout or self._timeout)

    def raise_person_version(
        self, request: RaisePersonVersionRequest, timeout: float | None = None
    ) -> RaisePersonVersionResponse:
        if self._leader_stub is None:
            raise PersonHogLifecycleUnavailable("personhog leader path not configured (PERSONHOG_LIFECYCLE_ADDR)")
        # The router routes leader calls by these headers, never by the request body.
        return self._leader_stub.RaisePersonVersion(
            request,
            timeout=timeout or self._timeout,
            metadata=[("x-team-id", str(request.team_id)), ("x-person-id", str(request.person_id))],
        )

    def restore_persons(self, request: RestorePersonsRequest, timeout: float | None = None) -> RestorePersonsResponse:
        return self._stub.RestorePersons(request, timeout=timeout or self._timeout)

    def write_distinct_ids(
        self, request: WriteDistinctIdsRequest, timeout: float | None = None
    ) -> WriteDistinctIdsResponse:
        return self._stub.WriteDistinctIds(request, timeout=timeout or self._timeout)

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

    def count_cohort_members(self, request: CountCohortMembersRequest) -> CountCohortMembersResponse:
        return self._stub.CountCohortMembers(request, timeout=self._timeout)

    def delete_cohort_member(
        self, request: DeleteCohortMemberRequest, timeout: float | None = None
    ) -> DeleteCohortMemberResponse:
        return self._stub.DeleteCohortMember(request, timeout=timeout or self._timeout)

    def delete_cohort_members_bulk(
        self, request: DeleteCohortMembersBulkRequest, timeout: float | None = None
    ) -> DeleteCohortMembersBulkResponse:
        return self._stub.DeleteCohortMembersBulk(request, timeout=timeout or self._timeout)

    def insert_cohort_members(
        self, request: InsertCohortMembersRequest, timeout: float | None = None
    ) -> InsertCohortMembersResponse:
        return self._stub.InsertCohortMembers(request, timeout=timeout or self._timeout)

    def list_cohort_member_ids(self, request: ListCohortMemberIdsRequest) -> ListCohortMemberIdsResponse:
        return self._stub.ListCohortMemberIds(request, timeout=self._timeout)

    # -- Groups --

    def get_group(self, request: GetGroupRequest) -> GetGroupResponse:
        return self._stub.GetGroup(request, timeout=self._timeout)

    def get_groups(self, request: GetGroupsRequest) -> GroupsResponse:
        return self._stub.GetGroups(request, timeout=self._timeout)

    def get_groups_batch(self, request: GetGroupsBatchRequest) -> GetGroupsBatchResponse:
        return self._stub.GetGroupsBatch(request, timeout=self._timeout)

    def list_groups(self, request: ListGroupsRequest) -> ListGroupsResponse:
        return self._stub.ListGroups(request, timeout=self._timeout)

    def create_group(self, request: CreateGroupRequest) -> CreateGroupResponse:
        return self._stub.CreateGroup(request, timeout=self._timeout)

    def update_group(self, request: UpdateGroupRequest) -> UpdateGroupResponse:
        return self._stub.UpdateGroup(request, timeout=self._timeout)

    def delete_groups_batch_for_team(
        self, request: DeleteGroupsBatchForTeamRequest, timeout: float | None = None
    ) -> DeleteGroupsBatchForTeamResponse:
        return self._stub.DeleteGroupsBatchForTeam(request, timeout=timeout or self._timeout)

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

    def get_group_type_mapping_by_dashboard_id(
        self, request: GetGroupTypeMappingByDashboardIdRequest
    ) -> GetGroupTypeMappingByDashboardIdResponse:
        return self._stub.GetGroupTypeMappingByDashboardId(request, timeout=self._timeout)

    def count_group_type_mappings(self, request: CountGroupTypeMappingsRequest) -> CountGroupTypeMappingsResponse:
        return self._stub.CountGroupTypeMappings(request, timeout=self._timeout)

    def update_group_type_mapping(self, request: UpdateGroupTypeMappingRequest) -> UpdateGroupTypeMappingResponse:
        return self._stub.UpdateGroupTypeMapping(request, timeout=self._timeout)

    def delete_group_type_mapping(self, request: DeleteGroupTypeMappingRequest) -> DeleteGroupTypeMappingResponse:
        return self._stub.DeleteGroupTypeMapping(request, timeout=self._timeout)

    def delete_group_type_mappings_batch_for_team(
        self, request: DeleteGroupTypeMappingsBatchForTeamRequest, timeout: float | None = None
    ) -> DeleteGroupTypeMappingsBatchForTeamResponse:
        return self._stub.DeleteGroupTypeMappingsBatchForTeam(request, timeout=timeout or self._timeout)

    # -- Feature flag hash key overrides --

    def delete_hash_key_overrides_by_teams(
        self, request: DeleteHashKeyOverridesByTeamsRequest, timeout: float | None = None
    ) -> DeleteHashKeyOverridesByTeamsResponse:
        return self._stub.DeleteHashKeyOverridesByTeams(request, timeout=timeout or self._timeout)


_T = TypeVar("_T")

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
                lifecycle_addr = getattr(settings, "PERSONHOG_LIFECYCLE_ADDR", "")
                client_name = getattr(settings, "OTEL_SERVICE_NAME", None) or "posthog-django"
                _client = PersonHogClient(
                    addr=addr,
                    client_name=client_name,
                    timeout_ms=timeout_ms,
                    lifecycle_addr=lifecycle_addr,
                    lifecycle_timeout_ms=getattr(settings, "PERSONHOG_LIFECYCLE_TIMEOUT_MS", 45_000),
                    keepalive_time_ms=getattr(settings, "PERSONHOG_KEEPALIVE_TIME_MS", 30_000),
                    keepalive_timeout_ms=getattr(settings, "PERSONHOG_KEEPALIVE_TIMEOUT_MS", 5_000),
                    keepalive_without_calls=getattr(settings, "PERSONHOG_KEEPALIVE_WITHOUT_CALLS", True),
                    max_reconnect_backoff_ms=getattr(settings, "PERSONHOG_MAX_RECONNECT_BACKOFF_MS", 5_000),
                    initial_reconnect_backoff_ms=getattr(settings, "PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS", 1_000),
                    max_send_message_length=getattr(settings, "PERSONHOG_MAX_SEND_MESSAGE_LENGTH", 4 * 1024 * 1024),
                    max_recv_message_length=getattr(settings, "PERSONHOG_MAX_RECV_MESSAGE_LENGTH", 128 * 1024 * 1024),
                    client_idle_timeout_ms=getattr(settings, "PERSONHOG_CLIENT_IDLE_TIMEOUT_MS", 0),
                    max_retries=getattr(settings, "PERSONHOG_MAX_RETRIES", 1),
                    initial_backoff_ms=getattr(settings, "PERSONHOG_INITIAL_BACKOFF_MS", 50),
                    max_backoff_ms=getattr(settings, "PERSONHOG_MAX_BACKOFF_MS", 1000),
                )
                logger.info(
                    "personhog_client_initialized", addr=addr, timeout_ms=timeout_ms, lifecycle_addr=lifecycle_addr
                )

    return _client


def require_personhog_client() -> PersonHogClient:
    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")
    return client


def personhog_call(
    operation: str,
    fn: Callable[[], _T],
    *,
    caller_tag: str | None = None,
    reraise_as: type[Exception] | None = None,
) -> _T:
    """Execute a personhog operation with metrics and optional error wrapping.

    ``caller_tag`` sets the personhog caller-tag context for observability.
    ``reraise_as`` wraps the exception in the given type before re-raising.
    Error metrics and a warning log are always recorded on failure regardless
    of ``reraise_as``.
    """
    from posthog.personhog_client.caller_tag import personhog_caller_tag
    from posthog.personhog_client.metrics import (
        PERSONHOG_ROUTING_ERRORS_TOTAL,
        PERSONHOG_ROUTING_TOTAL,
        get_client_name,
    )

    tag_ctx = personhog_caller_tag(caller_tag) if caller_tag else None

    try:
        if tag_ctx:
            with tag_ctx:
                result = fn()
        else:
            result = fn()
    except Exception as exc:
        PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
            operation=operation, source="personhog", error_type="grpc_error", client_name=get_client_name()
        ).inc()
        logger.warning("personhog_%s_failure", operation, exc_info=True)
        if reraise_as is not None:
            raise reraise_as(f"personhog {operation} failed") from exc
        raise

    PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="personhog", client_name=get_client_name()).inc()
    return result
