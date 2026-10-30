from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from math import ceil
from time import monotonic, time_ns
from typing import cast

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, F, Func, IntegerField, JSONField, OuterRef, Subquery, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from clickhouse_driver import Client
from pydantic import BaseModel, Field

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY,
    PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX,
    PERSON_GROUP_MEMBERSHIP_TABLE,
)
from posthog.models.team import Team
from posthog.redis import get_client as get_redis_client

from products.customer_analytics.backend.logic.feature_gate import is_customer_analytics_active
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig

PAGE_SIZE = 100
BATCH_SIZE = 500
WINDOW_SIZE = timedelta(days=1)
HISTORICAL_WINDOW_SIZE = timedelta(days=90)
QUERY_SETTINGS = {
    "max_execution_time": 120,
    "max_bytes_to_read": 50 * 1024**4,
    "max_result_bytes": 8_000_000,
    "result_overflow_mode": "throw",
    "distributed_foreground_insert": 1,
}


class MembershipReadiness(StrEnum):
    PENDING_CONFIG = "pending_config"
    BACKFILLING = "backfilling"
    CATCHING_UP = "catching_up"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


class MembershipState(BaseModel):
    group_type_index: int = Field(default=0, ge=0, le=PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX)
    version: int = Field(default=0, ge=0)
    status: MembershipReadiness = MembershipReadiness.DISABLED
    synced_at: datetime | None = None
    updated_at: datetime | None = None
    error_type: str = Field(default="", max_length=128)


def get_membership_properties_update(updates: Mapping[str, object]) -> Func:
    membership = CombinedExpression(
        Coalesce(F("properties__membership"), Value({}, output_field=JSONField())),
        "||",
        Value(dict(updates), output_field=JSONField()),
        output_field=JSONField(),
    )
    return Func(F("properties"), Value(["membership"]), membership, function="jsonb_set", output_field=JSONField())


@frozen
class MembershipTeam:
    team_id: int
    version: int = 0
    account_keys: tuple[str, ...] = ()
    dry_run: bool = False
    cursor: "MembershipCursor | None" = None


@frozen
class MembershipSyncPage:
    teams: tuple[MembershipTeam, ...]
    next_team_id: int | None
    candidates: int
    enabled: int
    changed: int


@frozen(frozen=False)
class MembershipCursor:
    team_id: int
    version: int
    group_type_index: int
    status: str = "backfilling"
    account_keys: tuple[str, ...] = ()
    dry_run: bool = False
    historical_start: datetime | None = None
    historical_end: datetime | None = None
    next_window_start: datetime | None = None
    next_window_end: datetime | None = None
    current_group_key: str = ""
    catch_up_end: datetime | None = None
    last_distinct_id: str = ""
    last_group_key: str = ""
    pending_group_keys: tuple[str, ...] = ()
    discovery_window_end: datetime | None = None
    snapshot_end: datetime | None = None
    error_type: str = ""
    accounts_completed: int = 0
    windows_completed: int = 0
    rows_written: int = 0
    rows_found: int = 0
    started_at: datetime | None = None
    last_batch_duration_seconds: float = 0
    lag_seconds: float = 0


@frozen
class MembershipStep:
    status: str
    rows: int = 0
    lag_seconds: float | None = None
    cursor: MembershipCursor | None = None


@frozen
class MembershipHistoryBounds:
    start: datetime | None
    end: datetime


@frozen
class MembershipPlan:
    team_id: int
    group_type_index: int
    historical_start: datetime | None
    historical_end: datetime
    estimated_events: int
    windows: int


@frozen
class MembershipRow:
    distinct_id: str
    group_key: str
    first_seen: datetime
    last_seen: datetime


def get_membership_group_type_indices(teams: Sequence[Team]) -> dict[int, int | None]:
    if not teams:
        return {}
    indices = dict(
        TeamCustomerAnalyticsConfig.objects.filter(
            team_id__in={team.parent_team_id or team.id for team in teams}
        ).values_list("team_id", "account_group_type_index")
    )
    active_organizations: dict[str, bool] = {}
    result: dict[int, int | None] = {}
    for team in teams:
        index = indices.get(team.parent_team_id or team.id)
        if index is None or not 0 <= index <= PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX:
            result[team.id] = None
            continue
        organization_id = str(team.organization_id)
        if organization_id not in active_organizations:
            active_organizations[organization_id] = is_customer_analytics_active(team, raise_on_unknown=True)
        result[team.id] = index if active_organizations[organization_id] else None
    return result


def get_membership_group_type_index(team: Team) -> int | None:
    return get_membership_group_type_indices([team])[team.id]


def get_membership_readiness(team: Team) -> str:
    if not is_customer_analytics_active(team):
        return MembershipReadiness.DISABLED
    index = get_membership_group_type_index(team)
    if index is None:
        return MembershipReadiness.PENDING_CONFIG
    config = TeamCustomerAnalyticsConfig.objects.filter(team_id=team.id).only("properties").first()
    state = MembershipState.model_validate(config.properties.get("membership", {})) if config else None
    if state is None or not state.version or state.group_type_index != index:
        return MembershipReadiness.PENDING_CONFIG
    return state.status


def get_window_end(start: datetime, end: datetime) -> datetime:
    return min(start + WINDOW_SIZE, end)


def get_historical_window_start(start: datetime, end: datetime) -> datetime:
    return max(start, end - HISTORICAL_WINDOW_SIZE)


def get_membership_group_column(group_type_index: int, *, native_json: bool) -> str:
    if group_type_index not in range(PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX + 1):
        raise ValueError("Invalid membership group type index")
    column = escape_clickhouse_identifier(f"$group_{group_type_index}")
    return f"properties.{column}" if native_json else column


def get_membership_batch_sql(*, group_type_index: int, catching_up: bool, native_json: bool = False) -> str:
    group_column = get_membership_group_column(group_type_index, native_json=native_json)
    if not catching_up:
        return f"""
            SELECT distinct_id, %(group_key)s AS group_key, min(timestamp), max(timestamp)
            FROM {events_read_table(native_json)}
            PREWHERE team_id = %(team_id)s
              AND timestamp >= %(start)s AND timestamp < %(end)s
              AND {group_column} = %(group_key)s
              AND person_mode != 'propertyless'
            WHERE distinct_id > %(last_distinct_id)s
              AND (inserted_at IS NULL OR inserted_at < %(snapshot_end)s)
            GROUP BY distinct_id ORDER BY distinct_id LIMIT {BATCH_SIZE}
        """
    return f"""
        SELECT distinct_id, {group_column} AS group_key,
               min(timestamp), max(timestamp)
        FROM {events_read_table(native_json)}
        WHERE team_id = %(team_id)s AND person_mode != 'propertyless'
          AND inserted_at >= %(start)s AND inserted_at < %(end)s
          AND notEmpty(group_key)
          AND (empty(%(account_keys)s) OR group_key IN %(account_keys)s)
          AND (distinct_id, group_key) > (%(last_distinct_id)s, %(last_group_key)s)
        GROUP BY team_id, distinct_id, group_key
        ORDER BY distinct_id, group_key
        LIMIT {BATCH_SIZE}
    """


class MembershipBackfillService:
    def __init__(self, *, deadline: float | None = None, should_stop: Callable[[], bool] | None = None) -> None:
        self.deadline = deadline
        self.should_stop = should_stop

    def check_attempt(self) -> None:
        if (self.deadline is not None and monotonic() >= self.deadline) or (self.should_stop and self.should_stop()):
            raise RuntimeError("Membership backfill attempt expired")

    def query(
        self, sql: str, params: Mapping[str, object] | list[tuple[object, ...]], *, team_id: int | None = None
    ) -> list[tuple[object, ...]]:
        self.check_attempt()
        query_settings = dict(QUERY_SETTINGS)
        if self.deadline is not None:
            query_settings["max_execution_time"] = min(120, max(1, int(self.deadline - monotonic())))
        with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY):
            rows = cast(
                list[tuple[object, ...]],
                sync_execute(sql, params, settings=query_settings, team_id=team_id, workload=Workload.OFFLINE) or [],
            )
        self.check_attempt()
        return rows

    def get_history_bounds(
        self, team_id: int, index: int, end: datetime, account_keys: tuple[str, ...] = ()
    ) -> MembershipHistoryBounds:
        native_json = use_new_events_schema(team_id)
        table = events_read_table(native_json)
        group_column = get_membership_group_column(index, native_json=native_json)
        days = []
        for direction in ("ASC", "DESC"):
            rows = self.query(
                f"""SELECT toDate(timestamp) AS event_date FROM {table}
                    WHERE team_id = %(team_id)s
                      AND (inserted_at IS NULL OR inserted_at < %(snapshot_end)s)
                      AND person_mode != 'propertyless'
                      AND notEmpty({group_column})
                      AND (empty(%(account_keys)s) OR {group_column} IN %(account_keys)s)
                    ORDER BY event_date {direction} LIMIT 1
                    SETTINGS optimize_read_in_order = 1""",
                {"team_id": team_id, "snapshot_end": end, "account_keys": list(account_keys)},
                team_id=team_id,
            )
            if not rows:
                return MembershipHistoryBounds(start=None, end=end)
            days.append(datetime.combine(cast(date, rows[0][0]), datetime.min.time(), tzinfo=UTC))
        return MembershipHistoryBounds(start=days[0], end=max(end, days[1] + timedelta(days=1)))

    def plan(self, team: Team, index: int, end: datetime, account_keys: tuple[str, ...] = ()) -> MembershipPlan:
        bounds = self.get_history_bounds(team.id, index, end, account_keys)
        native_json = use_new_events_schema(team.id)
        group_column = get_membership_group_column(index, native_json=native_json)
        start: datetime | None = None
        history_end = end
        estimated_events = 0
        window_end = bounds.end
        while bounds.start is not None and window_end > bounds.start:
            window_start = get_historical_window_start(bounds.start, window_end)
            rows = self.query(
                f"""SELECT minOrNull(timestamp), maxOrNull(timestamp), count() FROM {events_read_table(native_json)}
                    PREWHERE team_id = %(team_id)s
                      AND timestamp >= %(start)s AND timestamp < %(end)s
                    WHERE (inserted_at IS NULL OR inserted_at < %(snapshot_end)s)
                      AND person_mode != 'propertyless'
                      AND notEmpty({group_column})
                      AND (empty(%(account_keys)s) OR {group_column} IN %(account_keys)s)""",
                {
                    "team_id": team.id,
                    "start": window_start,
                    "end": window_end,
                    "snapshot_end": end,
                    "account_keys": list(account_keys),
                },
                team_id=team.id,
            )
            first_timestamp = cast(datetime | None, rows[0][0])
            if first_timestamp is not None:
                start = first_timestamp.replace(tzinfo=UTC)
                last_timestamp = cast(datetime, rows[0][1]).replace(tzinfo=UTC, microsecond=0)
                history_end = max(history_end, last_timestamp + timedelta(seconds=1))
            estimated_events += cast(int, rows[0][2])
            window_end = window_start
        return MembershipPlan(
            team_id=team.id,
            group_type_index=index,
            historical_start=start,
            historical_end=history_end,
            estimated_events=estimated_events,
            windows=max(0, ceil((history_end - start) / HISTORICAL_WINDOW_SIZE)) if start else 0,
        )

    def sync_page(self, after_team_id: int, *, dry_run: bool) -> MembershipSyncPage:
        self.check_attempt()
        configured = TeamCustomerAnalyticsConfig.objects.filter(
            team_id=Coalesce(OuterRef("parent_team_id"), OuterRef("id")),
            account_group_type_index__isnull=False,
        )
        config_ids = list(
            Team.objects.filter(id__gt=after_team_id)
            .filter(Exists(configured))
            .order_by("id")
            .values_list("id", flat=True)[:PAGE_SIZE]
        )
        registry_rows = self.query(
            f"""SELECT team_id, argMax(tuple(group_type_index, enabled, version), version) AS config
                FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}
                WHERE team_id > %(after)s GROUP BY team_id
                HAVING config.2 = 1 ORDER BY team_id LIMIT {PAGE_SIZE}""",
            {"after": after_team_id},
        )
        team_ids = sorted(set(config_ids) | {cast(int, row[0]) for row in registry_rows})[:PAGE_SIZE]
        current_rows = (
            self.query(
                f"""SELECT team_id, argMax(tuple(group_type_index, enabled, version), version)
                FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}
                WHERE team_id IN %(team_ids)s GROUP BY team_id""",
                {"team_ids": team_ids},
            )
            if team_ids
            else []
        )
        current = {cast(int, row[0]): cast(tuple[int, int, int], row[1]) for row in current_rows}
        teams = {team.id: team for team in Team.objects.filter(id__in=team_ids)}
        indices = get_membership_group_type_indices(list(teams.values()))
        pending = []
        enabled = changed = 0
        for team_id in team_ids:
            self.check_attempt()
            team = teams.get(team_id)
            index = indices.get(team_id)
            enabled += int(index is not None)
            existing = current.get(team_id)
            changed += int(
                (index is not None, index)
                != (bool(existing and existing[1]), existing[0] if existing and existing[1] else None)
            )
            if dry_run:
                continue
            if team is None:
                if existing:
                    self.write_registry(team_id, existing[0], False, max(time_ns() // 1000, existing[2] + 1))
                continue
            state = self.sync_team(team, index, existing)
            if index is not None and state.status != MembershipReadiness.READY:
                pending.append(MembershipTeam(team_id=team_id, version=state.version))
        return MembershipSyncPage(
            teams=tuple(pending),
            next_team_id=team_ids[-1] if len(team_ids) == PAGE_SIZE else None,
            candidates=len(team_ids),
            enabled=enabled,
            changed=changed,
        )

    def write_registry(self, team_id: int, index: int, enabled: bool, version: int) -> None:
        self.query(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} (team_id, group_type_index, enabled, version) VALUES",
            [(team_id, index, int(enabled), version)],
            team_id=team_id,
        )

    def configure_team(self, team: Team, index: int | None, existing: tuple[int, int, int] | None) -> MembershipState:
        self.check_attempt()
        with transaction.atomic():
            config, _ = TeamCustomerAnalyticsConfig.objects.select_for_update().get_or_create(team_id=team.id)
            self.check_attempt()
            state = MembershipState.model_validate(config.properties.get("membership", {}))
            reset = index is not None and (
                state.version == 0
                or state.group_type_index != index
                or state.status == MembershipReadiness.DISABLED
                or existing is None
                or existing[0] != index
                or not existing[1]
            )
            disable = index is None and (state.version == 0 or state.status != MembershipReadiness.DISABLED)
            if reset or disable:
                state.version = max(time_ns() // 1000, state.version + 1, existing[2] + 1 if existing else 1)
                state.group_type_index = index if index is not None else state.group_type_index
                state.status = MembershipReadiness.BACKFILLING if reset else MembershipReadiness.DISABLED
                state.error_type = ""
                state.synced_at = None
                self.check_attempt()
                state.updated_at = timezone.now()
                TeamCustomerAnalyticsConfig.objects.filter(team_id=team.id).update(
                    properties=get_membership_properties_update(state.model_dump(mode="json"))
                )
        return state

    def sync_registry(
        self, team: Team, state: MembershipState, index: int | None, existing: tuple[int, int, int] | None
    ) -> MembershipState:
        if (
            state.synced_at is None
            or existing is None
            or existing != (state.group_type_index, int(index is not None), state.version)
        ):
            self.write_registry(team.id, state.group_type_index, index is not None, state.version)
            self.check_attempt()
            synced_at = timezone.now()
            updated = TeamCustomerAnalyticsConfig.objects.filter(
                team_id=team.id, properties__membership__version=state.version
            ).update(properties=get_membership_properties_update({"synced_at": synced_at.isoformat()}))
            if updated:
                state.synced_at = synced_at
        return state

    def sync_team(self, team: Team, index: int | None, existing: tuple[int, int, int] | None) -> MembershipState:
        return self.sync_registry(team, self.configure_team(team, index, existing), index, existing)

    def prepare_backfill(self, input: MembershipTeam) -> MembershipTeam:
        self.check_attempt()
        if input.version or input.dry_run:
            return input
        team = Team.objects.get(id=input.team_id)
        index = get_membership_group_type_index(team)
        if index is None:
            return input
        rows = self.query(
            f"""SELECT argMax(tuple(group_type_index, enabled, version), version)
                FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} WHERE team_id = %(team_id)s""",
            {"team_id": team.id},
            team_id=team.id,
        )
        existing = cast(tuple[int, int, int], rows[0][0]) if rows else None
        state = self.configure_team(team, index, existing)
        return replace(input, version=state.version)

    def get_active_state(self, team_id: int, version: int) -> MembershipState | None:
        self.check_attempt()
        configured_index = TeamCustomerAnalyticsConfig.objects.filter(
            team_id=Coalesce(OuterRef("team__parent_team_id"), OuterRef("team_id"))
        ).values("account_group_type_index")[:1]
        config = (
            TeamCustomerAnalyticsConfig.objects.filter(team_id=team_id, properties__membership__version=version)
            .select_related("team")
            .annotate(membership_group_type_index=Cast("properties__membership__group_type_index", IntegerField()))
            .filter(
                membership_group_type_index=Subquery(configured_index),
                membership_group_type_index__lte=PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX,
            )
            .exclude(properties__membership__status=MembershipReadiness.DISABLED)
            .first()
        )
        if config is None:
            return None
        state = MembershipState.model_validate(config.properties.get("membership", {}))
        if not state.version or state.status == MembershipReadiness.DISABLED:
            return None
        if not is_customer_analytics_active(config.team, raise_on_unknown=True):
            return None
        return state

    @staticmethod
    def parse_membership_rows(rows: Sequence[tuple[object, ...]]) -> list[MembershipRow]:
        return [
            MembershipRow(
                distinct_id=cast(str, row[0]),
                group_key=cast(str, row[1]),
                first_seen=cast(datetime, row[2]),
                last_seen=cast(datetime, row[3]),
            )
            for row in rows
        ]

    def discover_accounts(self, state: MembershipCursor) -> bool:
        assert state.historical_start is not None and state.historical_end is not None
        if state.discovery_window_end is None:
            state.discovery_window_end = state.historical_end
        if state.discovery_window_end == state.historical_start:
            return False
        start = get_historical_window_start(state.historical_start, state.discovery_window_end)
        native_json = use_new_events_schema(state.team_id)
        group_column = get_membership_group_column(state.group_type_index, native_json=native_json)
        rows = self.query(
            f"""SELECT {group_column} AS group_key FROM {events_read_table(native_json)}
                PREWHERE team_id = %(team_id)s
                  AND timestamp >= %(start)s AND timestamp < %(end)s
                WHERE group_key > %(after)s AND person_mode != 'propertyless'
                  AND (inserted_at IS NULL OR inserted_at < %(snapshot_end)s)
                GROUP BY group_key ORDER BY group_key LIMIT {PAGE_SIZE}""",
            {
                "team_id": state.team_id,
                "start": start,
                "end": state.discovery_window_end,
                "snapshot_end": state.snapshot_end or state.historical_end,
                "after": state.last_group_key,
            },
            team_id=state.team_id,
        )
        state.pending_group_keys = tuple(
            sorted(set(state.pending_group_keys) | {cast(str, row[0]) for row in rows})[:PAGE_SIZE]
        )
        state.discovery_window_end = start
        self.save_progress(state)
        return start > state.historical_start

    def process_history(self, state: MembershipCursor) -> MembershipStep:
        assert state.historical_end is not None
        snapshot_end = state.snapshot_end or state.historical_end
        if state.historical_start is not None and not state.current_group_key:
            if state.account_keys:
                accounts = tuple(key for key in state.account_keys if key > state.last_group_key)[:1]
            else:
                if self.discover_accounts(state):
                    return MembershipStep(status=MembershipReadiness.BACKFILLING)
                accounts = state.pending_group_keys[:1]
                state.pending_group_keys = state.pending_group_keys[1:]
            if accounts:
                state.current_group_key = accounts[0]
                state.next_window_end = state.historical_end
                self.save_progress(state)
        if not state.current_group_key:
            if state.dry_run:
                state.status = "completed"
                return MembershipStep(status=state.status)
            state.status = MembershipReadiness.CATCHING_UP
            self.save_progress(state)
            if not self.dictionary_visible(state.team_id, state.group_type_index):
                return MembershipStep(
                    status="waiting_for_dictionary",
                    lag_seconds=max(0, (timezone.now() - snapshot_end).total_seconds()),
                )
            state.catch_up_end = timezone.now()
            state.next_window_start = snapshot_end - timedelta(minutes=5)
            state.last_distinct_id = state.last_group_key = ""
            self.save_progress(state)
            return MembershipStep(status=state.status)
        assert state.historical_start is not None and state.next_window_end is not None
        start = get_historical_window_start(state.historical_start, state.next_window_end)
        rows = self.parse_membership_rows(
            self.query(
                get_membership_batch_sql(
                    group_type_index=state.group_type_index,
                    catching_up=False,
                    native_json=use_new_events_schema(state.team_id),
                ),
                {
                    "team_id": state.team_id,
                    "group_key": state.current_group_key,
                    "start": start,
                    "end": state.next_window_end,
                    "snapshot_end": snapshot_end,
                    "last_distinct_id": state.last_distinct_id,
                },
                team_id=state.team_id,
            )
        )
        state.rows_found += len(rows)
        written = self.insert_memberships(state, rows)
        if len(rows) == BATCH_SIZE:
            state.last_distinct_id = rows[-1].distinct_id
        else:
            state.last_distinct_id = ""
            state.next_window_start = state.next_window_end = start
            state.windows_completed += 1
            if start == state.historical_start:
                state.accounts_completed += 1
                state.last_group_key = state.current_group_key
                state.current_group_key = ""
                state.next_window_end = None
                if not state.pending_group_keys:
                    state.discovery_window_end = None
        state.status = MembershipReadiness.BACKFILLING
        state.error_type = ""
        self.save_progress(state)
        return MembershipStep(status=state.status, rows=written)

    def create_cursor(self, input: MembershipTeam) -> MembershipCursor | None:
        team = Team.objects.filter(id=input.team_id).first()
        index = get_membership_group_type_index(team) if team else None
        if team is None or index is None:
            return None
        version = input.version
        if not input.dry_run:
            prepared = self.prepare_backfill(input)
            config = self.get_active_state(team.id, prepared.version)
            if config is None:
                return None
            self.sync_registry(team, config, index, None)
            version = config.version
        end = timezone.now()
        bounds = self.get_history_bounds(team.id, index, end, input.account_keys)
        return MembershipCursor(
            team_id=team.id,
            version=version,
            group_type_index=index,
            account_keys=tuple(sorted(set(input.account_keys))),
            dry_run=input.dry_run,
            historical_start=bounds.start,
            historical_end=bounds.end,
            snapshot_end=end,
            next_window_start=bounds.start or end,
            started_at=end,
        )

    def process_batch(self, input: MembershipTeam) -> MembershipStep:
        self.check_attempt()
        state = replace(input.cursor) if input.cursor else self.create_cursor(input)
        if state is None:
            return MembershipStep(status=MembershipReadiness.DISABLED)
        if not state.dry_run and self.get_active_state(state.team_id, state.version) is None:
            return MembershipStep(status=MembershipReadiness.DISABLED, cursor=state)
        result = self.process_cursor(state)
        state.rows_written += result.rows
        return replace(result, cursor=state)

    @classmethod
    def process_activity_batch(
        cls, input: MembershipTeam, *, deadline: float, should_stop: Callable[[], bool]
    ) -> MembershipStep:
        lease = get_redis_client(socket_timeout=2, socket_connect_timeout=2).lock(
            f"customer_analytics:membership_backfill:{input.team_id}", timeout=330, blocking_timeout=120
        )
        if not lease.acquire():
            raise RuntimeError("Another membership backfill attempt is active")
        try:
            service = cls(deadline=deadline, should_stop=lambda: should_stop() or not lease.owned())
            result = service.process_batch(input)
            service.check_attempt()
            return result
        finally:
            if lease.owned():
                lease.release()

    def process_cursor(self, state: MembershipCursor) -> MembershipStep:
        team_id = state.team_id
        assert state.historical_end is not None and state.next_window_start is not None
        if state.catch_up_end is None:
            return self.process_history(state)
        end = state.catch_up_end
        if state.next_window_start >= end:
            if not self.dictionary_visible(team_id, state.group_type_index):
                return MembershipStep(
                    status="waiting_for_dictionary", lag_seconds=(timezone.now() - end).total_seconds()
                )
            state.status = MembershipReadiness.READY
            state.error_type = ""
            self.save_progress(state)
            return MembershipStep(status=state.status)
        window_end = get_window_end(state.next_window_start, end)
        rows = self.parse_membership_rows(
            self.query(
                get_membership_batch_sql(
                    group_type_index=state.group_type_index,
                    catching_up=True,
                    native_json=use_new_events_schema(team_id),
                ),
                {
                    "team_id": team_id,
                    "start": state.next_window_start,
                    "end": window_end,
                    "last_distinct_id": state.last_distinct_id,
                    "last_group_key": state.last_group_key,
                    "account_keys": list(state.account_keys),
                },
                team_id=team_id,
            )
        )
        state.rows_found += len(rows)
        written = self.insert_memberships(state, rows)
        if len(rows) == BATCH_SIZE:
            state.last_distinct_id, state.last_group_key = rows[-1].distinct_id, rows[-1].group_key
        else:
            state.next_window_start = window_end
            state.windows_completed += 1
            state.last_distinct_id = state.last_group_key = ""
        state.status = MembershipReadiness.CATCHING_UP
        state.error_type = ""
        self.save_progress(state)
        return MembershipStep(
            status=state.status, rows=written, lag_seconds=max(0, (timezone.now() - window_end).total_seconds())
        )

    def insert_memberships(self, state: MembershipCursor, rows: Sequence[MembershipRow]) -> int:
        if not rows or state.dry_run:
            return 0
        persons = get_persons_mapped_by_distinct_id(state.team_id, list({row.distinct_id for row in rows}))
        admitted = [row for row in rows if row.distinct_id in persons and persons[row.distinct_id].is_identified]
        if not admitted or self.get_active_state(state.team_id, state.version) is None:
            return 0
        self.query(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES",
            [
                (state.team_id, state.group_type_index, row.group_key, row.distinct_id, row.first_seen, row.last_seen)
                for row in admitted
            ],
            team_id=state.team_id,
        )
        return len(admitted)

    def save_progress(self, state: MembershipCursor) -> None:
        self.check_attempt()
        if state.dry_run or state.account_keys:
            return
        updated = (
            TeamCustomerAnalyticsConfig.objects.filter(
                team_id=state.team_id, properties__membership__version=state.version
            )
            .exclude(properties__membership__status=MembershipReadiness.DISABLED)
            .update(
                properties=get_membership_properties_update(
                    {
                        "status": MembershipReadiness(state.status),
                        "error_type": state.error_type,
                        "updated_at": timezone.now().isoformat(),
                    }
                )
            )
        )
        if not updated:
            raise RuntimeError("Membership configuration changed during this batch")

    @staticmethod
    def fail(team_id: int, version: int, error_type: str) -> None:
        TeamCustomerAnalyticsConfig.objects.filter(team_id=team_id, properties__membership__version=version).exclude(
            properties__membership__status__in=[MembershipReadiness.READY, MembershipReadiness.DISABLED]
        ).update(
            properties=get_membership_properties_update(
                {
                    "status": MembershipReadiness.FAILED,
                    "error_type": error_type[:128],
                    "updated_at": timezone.now().isoformat(),
                }
            )
        )

    def dictionary_visible(self, team_id: int, index: int) -> bool:
        self.check_attempt()
        sql = """SELECT dictGet(%(dictionary)s, 'enabled', tuple(toInt64(%(team_id)s))),
                        dictGet(%(dictionary)s, 'group_type_index', tuple(toInt64(%(team_id)s)))"""
        params = {
            "dictionary": f"{settings.CLICKHOUSE_DATABASE}.{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}",
            "team_id": team_id,
        }
        if not settings.CLOUD_DEPLOYMENT and not settings.MULTINODE_CLICKHOUSE:
            return self.query(sql, params, team_id=team_id) == [(1, index)]

        def check(client: Client) -> bool:
            rows = client.execute(
                sql,
                params,
                settings={"max_execution_time": 15},
            )
            return rows == [(1, index)]

        results = (
            get_cluster(cluster=settings.CLICKHOUSE_MIGRATIONS_CLUSTER, data_cluster=settings.CLICKHOUSE_CLUSTER)
            .map_hosts_by_roles(check, [NodeRole.INGESTION_SMALL], concurrency=2, require_hosts=True)
            .result()
        )
        self.check_attempt()
        return bool(results) and all(results.values())
