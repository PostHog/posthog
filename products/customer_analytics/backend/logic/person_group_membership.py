from datetime import UTC, datetime, timedelta
from typing import Literal

from django.db import transaction
from django.utils import timezone

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_LIFETIME_MAX_SECONDS,
    PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX,
    PERSON_GROUP_MEMBERSHIP_TABLE,
)

from products.customer_analytics.backend.logic.eligibility import is_person_group_membership_eligible
from products.customer_analytics.backend.models import (
    PersonGroupMembershipState,
    PersonGroupMembershipStatus,
    TeamCustomerAnalyticsConfig,
)

PAGE_SIZE = 100
CHUNK_SIZE = timedelta(days=7)
CATCHUP_OVERLAP = timedelta(days=1)
QUERY_SETTINGS = {
    "max_execution_time": 600,
    "max_memory_usage": 4_000_000_000,
    "max_bytes_before_external_group_by": 1_000_000_000,
    "insert_distributed_sync": 1,
}
CONFIG_TABLE = escape_clickhouse_identifier(DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE)
MEMBERSHIP_TABLE = escape_clickhouse_identifier(PERSON_GROUP_MEMBERSHIP_TABLE)
CONFIG_INSERT_SQL = f"INSERT INTO {CONFIG_TABLE} (team_id, group_type_index, enabled, version) VALUES"


@frozen
class MembershipConfig:
    group_type_index: int
    enabled: bool
    version: int


@frozen
class MembershipSync:
    team_id: int
    config_version: int
    enabled: bool
    changed: bool
    needs_backfill: bool
    lag_seconds: float


@frozen
class MembershipBackfill:
    team_id: int
    config_version: int
    dry_run: bool = True


@frozen
class MembershipStep:
    status: Literal["continue", "waiting", "done"]
    wait_until: datetime | None = None


@frozen
class DateWindow:
    start: datetime
    end: datetime


def next_date_window(start: datetime, end: datetime) -> DateWindow | None:
    if start >= end:
        return None
    return DateWindow(start=start, end=min(start + CHUNK_SIZE, end))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _events_source(native_json: bool) -> str:
    return escape_clickhouse_identifier(events_read_table(native_json))


def read_membership_config(team_id: int) -> MembershipConfig | None:
    rows = sync_execute(
        f"SELECT argMax(tuple(group_type_index, enabled, version), version) FROM {CONFIG_TABLE} "
        "WHERE team_id = %(team_id)s GROUP BY team_id",
        {"team_id": team_id},
        team_id=team_id,
    )
    if not rows:
        return None
    index, enabled, version = rows[0][0]
    return MembershipConfig(group_type_index=index, enabled=bool(enabled), version=version)


def membership_candidate_page(after_team_id: int) -> list[int]:
    configured = (
        TeamCustomerAnalyticsConfig.objects.filter(team_id__gt=after_team_id, account_group_type_index__isnull=False)
        .order_by("team_id")
        .values_list("team_id", flat=True)[:PAGE_SIZE]
    )
    registered = sync_execute(
        f"SELECT team_id FROM {CONFIG_TABLE} WHERE team_id > %(after_team_id)s "
        "GROUP BY team_id HAVING argMax(enabled, version) = 1 ORDER BY team_id LIMIT %(limit)s",
        {"after_team_id": after_team_id, "limit": PAGE_SIZE},
    )
    return sorted(set(configured) | {row[0] for row in registered})[:PAGE_SIZE]


def sync_membership_team(team_id: int, *, dry_run: bool = True) -> MembershipSync:
    if dry_run:
        config = TeamCustomerAnalyticsConfig.objects.select_related("team").filter(team_id=team_id).first()
        index = config.account_group_type_index if config is not None else None
        enabled = config is not None and is_person_group_membership_eligible(config.team.organization_id, index)
        current = read_membership_config(team_id)
        changed = (current is None and enabled) or (
            current is not None and (current.enabled != enabled or (enabled and current.group_type_index != index))
        )
        return MembershipSync(
            team_id=team_id, config_version=0, enabled=enabled, changed=changed, needs_backfill=False, lag_seconds=0
        )

    PersonGroupMembershipState.objects.for_team(team_id, canonical=True).get_or_create(team_id=team_id)
    with transaction.atomic():
        state = PersonGroupMembershipState.objects.for_team(team_id, canonical=True).select_for_update().get()
        # The quiet state row serializes registry writes across overlapping coordinator activities.
        config = TeamCustomerAnalyticsConfig.objects.select_related("team").filter(team_id=team_id).first()
        index = config.account_group_type_index if config is not None else None
        enabled = config is not None and is_person_group_membership_eligible(config.team.organization_id, index)
        current = read_membership_config(team_id)
        changed = (current is None and enabled) or (
            current is not None and (current.enabled != enabled or (enabled and current.group_type_index != index))
        )
        repair = enabled and (
            state.config_version == 0
            or current is None
            or state.config_version != current.version
            or state.status == PersonGroupMembershipStatus.DISABLED
        )
        if changed or repair:
            now = timezone.now()
            version = max(
                int(now.timestamp() * 1000), state.config_version + 1, (current.version + 1) if current else 1
            )
            safe_index = index if enabled else (current.group_type_index if current else 0)
            safe_index = (
                safe_index
                if safe_index is not None and 0 <= safe_index <= PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX
                else 0
            )
            state.group_type_index = index if enabled else None
            state.config_version = version
            state.config_written_at = now
            state.status = (
                PersonGroupMembershipStatus.PENDING_CONFIG if enabled else PersonGroupMembershipStatus.DISABLED
            )
            state.historical_start = state.historical_end = state.next_window_start = None
            state.catchup_end = state.catchup_next_window_start = None
            state.last_error = ""
            state.save()
            sync_execute(
                CONFIG_INSERT_SQL,
                [(team_id, safe_index, int(enabled), version)],
                team_id=team_id,
                settings={"insert_distributed_sync": 1},
            )
        elif not enabled:
            state.status = PersonGroupMembershipStatus.DISABLED
            state.save()
        lag = (
            (timezone.now() - state.config_written_at).total_seconds()
            if state.config_written_at and state.status != PersonGroupMembershipStatus.READY
            else 0
        )
        return MembershipSync(
            team_id=team_id,
            config_version=state.config_version,
            enabled=enabled,
            changed=changed or repair,
            needs_backfill=enabled and state.status != PersonGroupMembershipStatus.READY,
            lag_seconds=max(0, lag),
        )


def insert_membership_window(team_id: int, group_type_index: int, window: DateWindow, *, catchup: bool = False) -> None:
    if not 0 <= group_type_index <= PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX:
        raise ValueError("Invalid account group type index")
    native_json = use_new_events_schema(team_id)
    properties = "toJSONString(properties)" if native_json else "properties"
    time_column = "created_at" if catchup else "timestamp"
    query = f"""
        INSERT INTO {MEMBERSHIP_TABLE}
            (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen)
        SELECT team_id, toUInt8(%(group_type_index)s) AS group_type_index,
            JSONExtractString({properties}, %(group_property)s) AS group_key,
            distinct_id, min(timestamp), max(timestamp)
        FROM {_events_source(native_json)}
        WHERE team_id = %(team_id)s AND {time_column} >= %(start)s AND {time_column} < %(end)s
            AND person_mode != 'propertyless' AND group_key != ''
        GROUP BY team_id, group_type_index, group_key, distinct_id
        """
    sync_execute(
        query,
        {
            "team_id": team_id,
            "group_type_index": group_type_index,
            "group_property": f"$group_{group_type_index}",
            "start": window.start,
            "end": window.end,
        },
        team_id=team_id,
        workload=Workload.OFFLINE,
        settings=QUERY_SETTINGS,
    )


def advance_membership_backfill(input: MembershipBackfill) -> MembershipStep:
    if input.dry_run:
        return MembershipStep(status="done")
    with transaction.atomic():
        state = PersonGroupMembershipState.objects.for_team(input.team_id, canonical=True).select_for_update().get()
        if state.config_version != input.config_version or state.status in {
            PersonGroupMembershipStatus.DISABLED,
            PersonGroupMembershipStatus.READY,
        }:
            return MembershipStep(status="done")
        config = TeamCustomerAnalyticsConfig.objects.select_related("team").filter(team_id=input.team_id).first()
        if (
            config is None
            or config.account_group_type_index != state.group_type_index
            or not is_person_group_membership_eligible(config.team.organization_id, config.account_group_type_index)
        ):
            return MembershipStep(status="done")
        if state.group_type_index is None or state.config_written_at is None:
            raise ValueError("Membership config has not been written")
        if state.historical_end is None:
            end = timezone.now()
            rows = sync_execute(
                f"SELECT minOrNull(timestamp) FROM {_events_source(use_new_events_schema(input.team_id))} "
                "WHERE team_id = %(team_id)s AND timestamp < %(end)s",
                {"team_id": input.team_id, "end": end},
                team_id=input.team_id,
                workload=Workload.OFFLINE,
                settings=QUERY_SETTINGS,
            )
            start = _utc(rows[0][0]) if rows[0][0] is not None else end
            state.historical_start = state.next_window_start = start
            state.historical_end = end
            state.status = PersonGroupMembershipStatus.BACKFILLING
            state.last_error = ""
            state.save()
            return MembershipStep(status="continue")
        assert state.next_window_start is not None
        window = next_date_window(state.next_window_start, state.historical_end)
        if window is not None:
            # Commit the cursor only after the synchronous Distributed insert finishes. Min/max makes replay safe.
            insert_membership_window(input.team_id, state.group_type_index, window)
            state.next_window_start = window.end
            state.status = PersonGroupMembershipStatus.BACKFILLING
            state.last_error = ""
            state.save()
            return MembershipStep(status="continue")
        visible_after = state.config_written_at + timedelta(
            seconds=PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_LIFETIME_MAX_SECONDS
        )
        if timezone.now() < visible_after:
            return MembershipStep(status="waiting", wait_until=visible_after)
        state.status = PersonGroupMembershipStatus.CATCHING_UP
        if state.catchup_end is None:
            state.catchup_end = timezone.now()
            # Ingest time catches late events with old activity timestamps during dictionary refresh.
            state.catchup_next_window_start = state.config_written_at - CATCHUP_OVERLAP
            state.save()
            return MembershipStep(status="continue")
        assert state.catchup_next_window_start is not None
        window = next_date_window(state.catchup_next_window_start, state.catchup_end)
        if window is not None:
            insert_membership_window(input.team_id, state.group_type_index, window, catchup=True)
            state.catchup_next_window_start = window.end
            state.last_error = ""
            state.save()
            return MembershipStep(status="continue")
        state.status = PersonGroupMembershipStatus.READY
        state.last_error = ""
        state.save()
        return MembershipStep(status="done")


def fail_membership_backfill(input: MembershipBackfill, error_type: str) -> None:
    PersonGroupMembershipState.objects.for_team(input.team_id, canonical=True).filter(
        config_version=input.config_version
    ).exclude(status__in=[PersonGroupMembershipStatus.DISABLED, PersonGroupMembershipStatus.READY]).update(
        status=PersonGroupMembershipStatus.FAILED, last_error=error_type[:200], updated_at=timezone.now()
    )


def is_person_group_membership_ready(team_id: int) -> bool:
    state = (
        PersonGroupMembershipState.objects.for_team(team_id, canonical=True)
        .filter(status=PersonGroupMembershipStatus.READY)
        .first()
    )
    if state is None:
        return False
    config = TeamCustomerAnalyticsConfig.objects.select_related("team").filter(team_id=state.team_id).first()
    return (
        config is not None
        and config.account_group_type_index == state.group_type_index
        and is_person_group_membership_eligible(config.team.organization_id, config.account_group_type_index)
    )
