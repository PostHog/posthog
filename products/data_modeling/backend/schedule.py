"""Load-spreading scheduler for data modeling (saved query) jobs.

Deterministic bucketing: Uses SHA-256 of entity_id + salt to derive
deterministic integers uniformly across all IDs

Frequency tiers:
- Short (15min, 30min, 1hr): ScheduleCalendarSpec with deterministic minute bucket + 1min jitter
- Medium (6hr, 12hr, 24hr): ScheduleCalendarSpec with deterministic hour bucket + 1hr jitter
- Weekly: ScheduleCalendarSpec with deterministic day (0-6) + hour (0-23) + 1hr jitter
- Monthly: ScheduleCalendarSpec with deterministic day (1-28) + hour (0-23) + 1hr jitter
"""

import uuid
import hashlib
from collections.abc import Collection
from datetime import timedelta
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from temporalio.client import ScheduleCalendarSpec, ScheduleListActionStartWorkflow, ScheduleRange, ScheduleSpec
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import (
    POSTHOG_DAG_ID_KEY,
    POSTHOG_ORG_ID_KEY,
    POSTHOG_SCHEDULE_TYPE_KEY,
    POSTHOG_TEAM_ID_KEY,
)

from products.data_modeling.backend.models import Node

if TYPE_CHECKING:
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

# v2 (DAG-based) schedules run this workflow; their schedule id is the bare DAG id, or
# "{dag_id}:{interval_seconds}" for a per-cadence-tier schedule. The v1 backend
# (`data-modeling-run`, one schedule per saved query) is frozen and being migrated away from.
DATA_MODELING_EXECUTE_DAG_WORKFLOW = "data-modeling-execute-dag"


def dag_schedule_search_attributes(*, team_id: int, organization_id: str, dag_id: str) -> TypedSearchAttributes:
    return TypedSearchAttributes(
        search_attributes=[
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
            SearchAttributePair(key=POSTHOG_ORG_ID_KEY, value=organization_id),
            SearchAttributePair(key=POSTHOG_DAG_ID_KEY, value=dag_id),
            SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=DATA_MODELING_EXECUTE_DAG_WORKFLOW),
        ]
    )


@async_to_sync
async def get_v2_scheduled_dag_ids(candidate_dag_ids: Collection[str] | None = None) -> set[str]:
    """Return the IDs of DAGs that already have a v2 `data-modeling-execute-dag` Temporal schedule.

    A DAG appearing here has been migrated off the frozen v1 backend. Callers performing v1
    schedule operations must skip these DAGs' saved queries so they never re-create or revive a
    v1 schedule for a DAG already running on v2.

    When `candidate_dag_ids` is given, the listing is scoped server-side to those DAGs via the
    `PostHogDagId` search attribute so we never paginate every schedule in the namespace — a
    single unscoped listing per saved-query operation is enough to exhaust the namespace rate
    limit once the schedule fleet is large. The None sweep filters on `PostHogScheduleType`
    (needs schedules backfilled with the tag).
    """
    if candidate_dag_ids is not None and not candidate_dag_ids:
        return set()

    temporal = await async_connect()
    if candidate_dag_ids is not None:
        # Filtering on a search attribute (PostHogDagId) is supported server-side; filtering on
        # WorkflowType is not, so we still narrow to the execute-dag workflow client-side below.
        quoted = ", ".join(f"'{dag_id}'" for dag_id in candidate_dag_ids)
        schedules = await temporal.list_schedules(query=f"{POSTHOG_DAG_ID_KEY.name} IN ({quoted})")
    else:
        schedules = await temporal.list_schedules(
            query=f'{POSTHOG_SCHEDULE_TYPE_KEY.name} = "{DATA_MODELING_EXECUTE_DAG_WORKFLOW}"'
        )

    dag_ids: set[str] = set()
    async for listing in schedules:
        action = listing.schedule.action if listing.schedule else None
        if (
            isinstance(action, ScheduleListActionStartWorkflow)
            and action.workflow == DATA_MODELING_EXECUTE_DAG_WORKFLOW
        ):
            # A cadence-tier schedule id is "{dag_id}:{interval_seconds}"; a legacy id is the
            # bare DAG id (no colon), which rsplit leaves untouched.
            dag_ids.add(listing.id.rsplit(":", 1)[0])
    return dag_ids


def get_v2_saved_query_ids(candidate_ids: Collection[uuid.UUID] | None = None) -> set[uuid.UUID]:
    """Return saved query IDs whose DAG already runs on a v2 schedule.

    Optionally restrict the lookup to `candidate_ids` to keep the query bounded. These saved
    queries must be skipped by v1 schedule commands so we never undo migration progress.
    """
    if candidate_ids is not None:
        if not candidate_ids:
            return set()
        # Resolve the candidate saved queries to their DAGs first so the Temporal lookup is scoped
        # to just those DAGs rather than listing every schedule in the namespace.
        dag_id_by_saved_query = {
            saved_query_id: str(dag_id)
            for saved_query_id, dag_id in Node.objects.filter(
                saved_query_id__in=candidate_ids, saved_query_id__isnull=False
            ).values_list("saved_query_id", "dag_id")
            if dag_id is not None
        }
        if not dag_id_by_saved_query:
            return set()

        v2_dag_ids = get_v2_scheduled_dag_ids(set(dag_id_by_saved_query.values()))
        return {saved_query_id for saved_query_id, dag_id in dag_id_by_saved_query.items() if dag_id in v2_dag_ids}

    v2_dag_ids = get_v2_scheduled_dag_ids()
    if not v2_dag_ids:
        return set()

    nodes = Node.objects.filter(dag_id__in=v2_dag_ids, saved_query_id__isnull=False)
    return set(nodes.values_list("saved_query_id", flat=True))


def partition_saved_queries_by_v2_schedule(
    saved_queries: list["DataWarehouseSavedQuery"],
) -> tuple[list["DataWarehouseSavedQuery"], list["DataWarehouseSavedQuery"]]:
    """Split saved queries into (v1_eligible, on_v2).

    A saved query is "on v2" when any DAG it belongs to already has a `data-modeling-execute-dag`
    schedule. v1 schedule commands should skip the on_v2 list so they do not undo migration progress.
    """
    if not saved_queries:
        return [], []

    v2_ids = get_v2_saved_query_ids([sq.id for sq in saved_queries])
    if not v2_ids:
        return list(saved_queries), []

    eligible = [sq for sq in saved_queries if sq.id not in v2_ids]
    on_v2 = [sq for sq in saved_queries if sq.id in v2_ids]
    return eligible, on_v2


def _deterministic_int(entity_id: uuid.UUID, salt: str) -> int:
    """SHA-256 based deterministic integer from entity_id + salt."""
    digest = hashlib.sha256(f"{entity_id}-{salt}".encode()).hexdigest()
    return int(digest[:16], 16)


def _short_interval_spec(entity_id: uuid.UUID, interval: timedelta, timezone: str) -> ScheduleSpec:
    """Short intervals (15min, 30min, 1hr): deterministic minute bucket + up to 1min jitter.

    Jitter spreads each run randomly within its assigned minute.
    """
    interval_mins = int(interval.total_seconds() // 60)
    num_windows = 60 // interval_mins
    base_min = _deterministic_int(entity_id, "minute") % interval_mins
    mins = [(base_min + i * interval_mins) % 60 for i in range(num_windows)]
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment=f"Every {base_min}th minute in the {interval_mins}min interval window (bucketed)",
                hour=[ScheduleRange(start=0, end=23)],
                minute=[ScheduleRange(start=m, end=m) for m in mins],
            )
        ],
        jitter=timedelta(minutes=1),
        time_zone_name=timezone,
    )


def _medium_interval_spec(entity_id: uuid.UUID, interval: timedelta, timezone: str) -> ScheduleSpec:
    """Medium intervals (6hr, 12hr, 24hr): deterministic hour bucket + up to 1hr jitter.

    For a 6hr interval: pick 1 of 6 hour-buckets and repeat 4x per day -> 6 distinct buckets.
    For a 12hr interval: pick 1 of 12 hour-buckets and repeat 2x -> 12 distinct buckets.
    For a 24hr interval: pick 1 of 24 hour-buckets -> 24 distinct buckets.

    Jitter spreads each run randomly within its assigned hour.
    """
    interval_hours = int(interval.total_seconds() // 3600)
    num_windows = 24 // interval_hours
    base_hour = _deterministic_int(entity_id, "hour") % interval_hours
    hours = [(base_hour + i * interval_hours) % 24 for i in range(num_windows)]
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment=f"Every {base_hour}th hour in the {interval_hours} interval window (bucketed)",
                hour=[ScheduleRange(start=h, end=h) for h in hours],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def _weekly_spec(entity_id: uuid.UUID, timezone: str) -> ScheduleSpec:
    """Weekly schedule: deterministic day-of-week (0-6) + hour (0-23) + minute (0-59)."""
    day_of_week = _deterministic_int(entity_id, "day") % 7
    hour = _deterministic_int(entity_id, "hour") % 24

    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment="Weekly (load-spread)",
                day_of_week=[ScheduleRange(start=day_of_week, end=day_of_week)],
                hour=[ScheduleRange(start=hour, end=hour)],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def _monthly_spec(entity_id: uuid.UUID, timezone: str) -> ScheduleSpec:
    """Monthly schedule: deterministic day-of-month (1-28) + hour (0-23) + minute (0-59)."""
    day_of_month = (_deterministic_int(entity_id, "day") % 28) + 1
    hour = _deterministic_int(entity_id, "hour") % 24

    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                comment="Monthly (load-spread)",
                day_of_month=[ScheduleRange(start=day_of_month, end=day_of_month)],
                hour=[ScheduleRange(start=hour, end=hour)],
            )
        ],
        jitter=timedelta(hours=1),
        time_zone_name=timezone,
    )


def build_schedule_spec(
    entity_id: uuid.UUID,
    interval: timedelta,
    team_timezone: str = "UTC",
) -> ScheduleSpec:
    """Build a Temporal ScheduleSpec for a saved query based on its sync frequency.

    Args:
        entity_id: The saved query UUID (used for deterministic bucketing).
        interval: The sync frequency interval (e.g. timedelta(hours=24)).
        team_timezone: The team's timezone (e.g. "America/New_York"). Used for 6hr+ schedules.

    Returns:
        A ScheduleSpec ready to be used with Temporal's Schedule API.
    """
    total_hours = interval.total_seconds() / 3600

    if total_hours <= 1:
        return _short_interval_spec(entity_id, interval, team_timezone)
    elif total_hours <= 24:
        return _medium_interval_spec(entity_id, interval, team_timezone)
    elif total_hours <= 168:
        return _weekly_spec(entity_id, team_timezone)
    else:
        return _monthly_spec(entity_id, team_timezone)
