from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal, TypedDict
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, QuerySet
from django.db.models.functions import TruncDate
from django.utils import timezone

from products.data_warehouse.backend.facade.contracts import LandingHistory, LandingHistoryBucket
from products.data_warehouse.backend.logic.backfill_status import historical_backfill_months
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition
from products.managed_warehouse.backend.facade import source_jobs
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobRecord,
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobWorkflow,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.facade.team_state import team_backfill_membership
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import (
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSourceAccessMethod,
)

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

ReadinessState = Literal[
    "not_configured",
    "waiting",
    "backfilling",
    "up_to_date",
    "needs_attention",
    "sync_paused",
]

LandingState = Literal["in_sync", "behind", "failing", "not_in_warehouse", "paused"]

# Worst first. A paused schema is intentional configuration, so a source with any active schema
# reports that schema's state, and only a fully paused source reports paused.
LANDING_PRIORITY: tuple[LandingState, ...] = ("failing", "behind", "not_in_warehouse", "in_sync", "paused")

# Upstream schema statuses that mean the import is not working. Mirrors what the pipeline status
# panel treats as a failing sync (a failed run, or a billing limit that stops runs).
FAILING_SYNC_STATUSES: frozenset[str] = frozenset(
    {
        ExternalDataSchemaStatus.FAILED,
        ExternalDataSchemaStatus.BILLING_LIMIT_REACHED,
        ExternalDataSchemaStatus.BILLING_LIMIT_TOO_LOW,
    }
)

# A paused schema is intentional configuration, so active and healthy schemas determine a source's
# rollup first. A source still reports sync_paused when every visible schema is paused.
READINESS_PRIORITY: tuple[ReadinessState, ...] = (
    "needs_attention",
    "backfilling",
    "waiting",
    "up_to_date",
    "sync_paused",
)


class DatasetStatus(TypedDict):
    dataset: Literal["events", "persons"]
    readiness_state: ReadinessState
    detail: str
    completed_partitions: int
    total_partitions: int | None
    current_partition: str | None
    last_updated_at: datetime | None
    landing_state: LandingState
    failed_partitions: int
    last_error: str | None
    last_completed_at: datetime | None
    latest_day_loaded: date | None


class SourceTableStatus(TypedDict):
    schema_id: str
    source_id: str
    source_name: str
    source_type: str
    table_name: str
    readiness_state: ReadinessState
    detail: str
    workflow_type: ManagedWarehouseSourceJobWorkflow | None
    workflow_status: ManagedWarehouseSourceJobStatus | None
    workflow_started_at: datetime | None
    applied: bool
    last_applied_at: datetime | None
    last_synced_at: datetime | None
    landing_state: LandingState
    pending_since: datetime | None
    workflow_finished_at: datetime | None
    workflow_error: str | None
    sync_status: str | None
    sync_error: str | None
    last_sync_rows: int | None


class LandingCounts(TypedDict):
    in_sync: int
    behind: int
    failing: int
    not_in_warehouse: int
    paused: int


class SourceSummary(TypedDict):
    source_id: str
    source_name: str
    source_type: str
    readiness_state: ReadinessState
    detail: str
    total_schemas: int
    applied_schemas: int
    last_applied_at: datetime | None
    last_synced_at: datetime | None
    landing_state: LandingState
    landing_counts: LandingCounts
    pending_since: datetime | None
    sync_failed_schemas: int


class SourcesStatus(TypedDict):
    readiness_state: ReadinessState
    detail: str
    sources: list[SourceSummary]


class ManagedWarehouseDataStatus(TypedDict):
    overall_readiness_state: ReadinessState
    events: DatasetStatus
    persons: DatasetStatus
    sources: SourcesStatus
    generated_at: datetime


def _event_historical_partition_count(backfill: ManagedWarehouseTeamMembership) -> int | None:
    if backfill.earliest_event_date is None:
        return None

    # Same helper the scheduler enqueues from, so this denominator always matches what actually runs.
    return len(historical_backfill_months(backfill.earliest_event_date))


def dataset_status(
    *,
    dataset: Literal["events", "persons"],
    backfill: ManagedWarehouseTeamMembership | None,
    partitions: list[ManagedWarehouseBackfillPartition],
) -> DatasetStatus:
    if backfill is None or not backfill.backfill_enabled:
        return {
            "dataset": dataset,
            "readiness_state": "not_configured",
            "detail": "Warehouse backfill is not enabled for this project. Enable it from the Settings tab.",
            "completed_partitions": 0,
            "total_partitions": None,
            "current_partition": None,
            "last_updated_at": None,
            "landing_state": "not_in_warehouse",
            "failed_partitions": 0,
            "last_error": None,
            "last_completed_at": None,
            "latest_day_loaded": None,
        }

    relevant_partitions = partitions
    # History is per-month for events and a single full export for persons. Both are read off the
    # granularity column rather than the key's spelling, so a scheduler that names its partitions
    # differently can't silently change what these numbers mean.
    if dataset == "events":
        historical_granularity = ManagedWarehouseBackfillPartition.Granularity.MONTH
        total_partitions = _event_historical_partition_count(backfill)
    else:
        historical_granularity = ManagedWarehouseBackfillPartition.Granularity.FULL
        total_partitions = 1

    historical_partitions = [row for row in partitions if row.granularity == historical_granularity]
    completed_partitions = sum(
        row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.COMPLETED
        for row in historical_partitions
    )

    failed = next(
        (
            row
            for row in relevant_partitions
            if row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.FAILED
        ),
        None,
    )
    running = next(
        (
            row
            for row in relevant_partitions
            if row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.RUNNING
        ),
        None,
    )
    last_updated_at = max((row.updated_at for row in relevant_partitions), default=None)
    completed_rows = [
        row
        for row in relevant_partitions
        if row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.COMPLETED
    ]
    failed_partitions = sum(
        row.lifecycle_state == ManagedWarehouseBackfillPartition.LifecycleState.FAILED for row in relevant_partitions
    )
    last_completed_at = max((row.completed_at for row in completed_rows if row.completed_at is not None), default=None)
    latest_day_loaded = max(
        (
            row.period_start
            for row in completed_rows
            if row.granularity == ManagedWarehouseBackfillPartition.Granularity.DAY and row.period_start is not None
        ),
        default=None,
    )

    if failed is not None:
        readiness_state: ReadinessState = "needs_attention"
        detail = "A backfill partition failed. Retry the failed warehouse backfill run."
        current_partition = failed.partition_key
    elif running is not None:
        readiness_state = "backfilling"
        detail = "Historical data is being copied into the warehouse."
        current_partition = running.partition_key
    elif total_partitions is None:
        readiness_state = "waiting"
        detail = "Preparing the historical data range."
        current_partition = None
    elif completed_partitions < total_partitions:
        readiness_state = "backfilling" if completed_partitions else "waiting"
        detail = f"{completed_partitions} of {total_partitions} historical partitions are complete."
        current_partition = None
    else:
        readiness_state = "up_to_date"
        detail = "Historical data is loaded and daily updates are enabled."
        current_partition = None

    landing_state: LandingState
    if failed is not None:
        landing_state = "failing"
    elif running is not None:
        landing_state = "behind"
    elif not completed_rows:
        landing_state = "not_in_warehouse"
    elif readiness_state == "up_to_date":
        landing_state = "in_sync"
    else:
        landing_state = "behind"

    return {
        "dataset": dataset,
        "readiness_state": readiness_state,
        "detail": detail,
        "completed_partitions": completed_partitions,
        "total_partitions": total_partitions,
        "current_partition": current_partition,
        "last_updated_at": last_updated_at,
        "landing_state": landing_state,
        "failed_partitions": failed_partitions,
        "last_error": failed.last_error if failed is not None else None,
        "last_completed_at": last_completed_at,
        "latest_day_loaded": latest_day_loaded,
    }


def source_table_readiness(state: ManagedWarehouseSourceJobRecord | None) -> tuple[ReadinessState, str]:
    if state is None:
        return "waiting", "Waiting for a copy or register workflow to run."

    workflow_name = state.workflow_type.value
    if state.status == ManagedWarehouseSourceJobStatus.FAILED:
        return "needs_attention", (
            f"The latest {workflow_name} workflow failed. To retry, select Sync now for this table on its source page."
        )
    if state.status == ManagedWarehouseSourceJobStatus.RUNNING:
        return "backfilling", f"The {workflow_name} workflow is applying the latest source import."
    if state.status == ManagedWarehouseSourceJobStatus.COMPLETED:
        return "up_to_date", "The latest source import was applied."
    if state.status == ManagedWarehouseSourceJobStatus.STALE:
        return "waiting", "A newer source import replaced this register workflow."
    return "waiting", f"The {workflow_name} workflow did not apply this source import."


def _landing_state(
    *, should_sync: bool, state: ManagedWarehouseSourceJobRecord | None, last_synced_at: datetime | None
) -> LandingState:
    if not should_sync:
        return "paused"
    if state is not None and state.status == ManagedWarehouseSourceJobStatus.FAILED:
        return "failing"
    last_applied_at = state.last_completed_at if state else None
    if last_applied_at is None:
        return "not_in_warehouse"
    if state is not None and state.status == ManagedWarehouseSourceJobStatus.RUNNING:
        return "behind"
    if last_synced_at is not None and last_synced_at > last_applied_at:
        return "behind"
    return "in_sync"


def _pending_since(
    *, should_sync: bool, last_synced_at: datetime | None, last_applied_at: datetime | None
) -> datetime | None:
    if not should_sync or last_synced_at is None:
        return None
    if last_applied_at is None or last_synced_at > last_applied_at:
        return last_synced_at
    return None


def _visible_schemas_queryset(
    team_id: int, *, user_access_control: UserAccessControl, source_id: str | None = None
) -> QuerySet[ExternalDataSchema]:
    source_filter: dict[str, object] = {
        "team_id": team_id,
        "deleted": False,
        "access_method": ExternalDataSourceAccessMethod.WAREHOUSE,
    }
    if source_id is not None:
        source_filter["id"] = source_id
    sources = user_access_control.filter_queryset_by_access_level(ExternalDataSource.objects.filter(**source_filter))
    return ExternalDataSchema.objects.filter(team_id=team_id, deleted=False, source__in=sources)


def _latest_sync_rows(team_id: int, schema_ids: list[UUID]) -> dict[UUID, int | None]:
    """Rows from each schema's most recent completed upstream import, in one query."""
    if not schema_ids:
        return {}
    latest = (
        ExternalDataJob.objects.filter(
            team_id=team_id, schema_id__in=schema_ids, status=ExternalDataJobStatus.COMPLETED
        )
        .order_by("schema_id", "-finished_at", "-created_at")
        .distinct("schema_id")
    )
    return dict(latest.values_list("schema_id", "rows_synced"))


def _schema_table_statuses(
    team_id: int, *, user_access_control: UserAccessControl, source_id: str | None = None
) -> list[SourceTableStatus]:
    """Per-schema readiness, optionally scoped to one source.

    Shared by the top-level rollup (all sources, for the Overview tab's summary card) and the
    per-source detail lookup (one source's schemas, for the drill-down modal) so the readiness
    computation and the visibility rules never drift between the two views.
    """
    schemas = list(
        _visible_schemas_queryset(team_id, user_access_control=user_access_control, source_id=source_id).select_related(
            "source"
        )
    )
    latest_jobs_by_schema = {
        state.schema_id: state
        for state in source_jobs.list_latest_source_jobs(team_id=team_id, schema_ids=[schema.id for schema in schemas])
    }

    last_sync_rows_by_schema = _latest_sync_rows(team_id, [schema.id for schema in schemas])

    tables: list[SourceTableStatus] = []
    for schema in schemas:
        state = latest_jobs_by_schema.get(schema.id)
        last_applied_at = state.last_completed_at if state else None
        workflow_failed = state is not None and state.status == ManagedWarehouseSourceJobStatus.FAILED
        sync_failing = schema.status in FAILING_SYNC_STATUSES
        if schema.should_sync:
            readiness_state, detail = source_table_readiness(state)
        else:
            readiness_state, detail = (
                "sync_paused",
                "Sync is paused for this table. Data already in the warehouse is unaffected.",
            )
        tables.append(
            {
                "schema_id": str(schema.id),
                "source_id": str(schema.source_id),
                "source_name": schema.source.prefix or schema.source.source_type,
                "source_type": schema.source.source_type,
                "table_name": schema.name,
                "readiness_state": readiness_state,
                "detail": detail,
                "workflow_type": state.workflow_type if state else None,
                "workflow_status": state.status if state else None,
                "workflow_started_at": state.started_at if state else None,
                "applied": state is not None and state.last_completed_at is not None,
                "last_applied_at": state.last_completed_at if state else None,
                "last_synced_at": schema.last_synced_at,
                "landing_state": _landing_state(
                    should_sync=schema.should_sync, state=state, last_synced_at=schema.last_synced_at
                ),
                "pending_since": _pending_since(
                    should_sync=schema.should_sync,
                    last_synced_at=schema.last_synced_at,
                    last_applied_at=last_applied_at,
                ),
                "workflow_finished_at": state.finished_at if state else None,
                "workflow_error": state.latest_error if state is not None and workflow_failed else None,
                "sync_status": schema.status,
                "sync_error": schema.latest_error if sync_failing else None,
                "last_sync_rows": last_sync_rows_by_schema.get(schema.id),
            }
        )
    return tables


def get_source_schema_statuses(
    team_id: int, source_id: str, *, user_access_control: UserAccessControl
) -> list[SourceTableStatus]:
    """Per-schema detail for one imported source — backs the Overview tab's drill-down modal."""
    return sort_source_tables(
        _schema_table_statuses(team_id, user_access_control=user_access_control, source_id=source_id)
    )


_SOURCE_SUMMARY_DETAILS: dict[ReadinessState, str] = {
    "needs_attention": "One or more schemas need attention.",
    "backfilling": "A copy or register workflow is running for one or more schemas.",
    "waiting": "One or more schemas are waiting to start.",
    "sync_paused": "Sync is paused for one or more schemas.",
    "up_to_date": "The latest source imports were applied to the warehouse.",
    "not_configured": "No schemas are configured for this source.",
}

_MAX_NAMED_TABLES = 3


def _source_summary_detail(readiness_state: ReadinessState, rows: list[SourceTableStatus]) -> str:
    attention = [row for row in rows if row["readiness_state"] == "needs_attention"]
    failed = [
        row["table_name"] for row in attention if row["workflow_status"] == ManagedWarehouseSourceJobStatus.FAILED
    ]
    if readiness_state != "needs_attention" or not failed or len(failed) != len(attention):
        return _SOURCE_SUMMARY_DETAILS[readiness_state]
    names = sorted(failed, key=lambda name: (name.lower(), name))
    hidden = len(names) - _MAX_NAMED_TABLES
    if hidden > 0:
        listed = f"{', '.join(names[:_MAX_NAMED_TABLES])} and {hidden} more"
    elif len(names) > 1:
        listed = f"{', '.join(names[:-1])} and {names[-1]}"
    else:
        listed = names[0]
    noun = "table" if len(names) == 1 else "tables"
    return f"The latest workflow failed for {len(names)} {noun}: {listed}. Select the source for details."


def _rollup_sources(tables: list[SourceTableStatus]) -> list[SourceSummary]:
    grouped: dict[str, list[SourceTableStatus]] = {}
    for table in tables:
        grouped.setdefault(table["source_id"], []).append(table)

    summaries: list[SourceSummary] = []
    for source_id, rows in grouped.items():
        readiness_state = _roll_up_state([row["readiness_state"] for row in rows])
        last_applied_at = max(
            (row["last_applied_at"] for row in rows if row["last_applied_at"] is not None), default=None
        )
        last_synced_at = max((row["last_synced_at"] for row in rows if row["last_synced_at"] is not None), default=None)
        landing_counts: LandingCounts = {
            "in_sync": 0,
            "behind": 0,
            "failing": 0,
            "not_in_warehouse": 0,
            "paused": 0,
        }
        for row in rows:
            landing_counts[row["landing_state"]] += 1
        landing_state: LandingState = next((state for state in LANDING_PRIORITY if landing_counts[state] > 0), "paused")
        summaries.append(
            {
                "source_id": source_id,
                "source_name": rows[0]["source_name"],
                "source_type": rows[0]["source_type"],
                "readiness_state": readiness_state,
                "detail": _source_summary_detail(readiness_state, rows),
                "total_schemas": len(rows),
                "applied_schemas": sum(1 for row in rows if row["applied"]),
                "last_applied_at": last_applied_at,
                "last_synced_at": last_synced_at,
                "landing_state": landing_state,
                "landing_counts": landing_counts,
                "pending_since": min(
                    (row["pending_since"] for row in rows if row["pending_since"] is not None), default=None
                ),
                "sync_failed_schemas": sum(
                    1
                    for row in rows
                    if row["sync_status"] in FAILING_SYNC_STATUSES and row["landing_state"] != "paused"
                ),
            }
        )
    return sort_sources(summaries)


def sort_sources(sources: list[SourceSummary]) -> list[SourceSummary]:
    """Most severe first, then alphabetically by source name — same rationale as sort_source_tables."""
    severity = {state: rank for rank, state in enumerate(READINESS_PRIORITY)}
    return sorted(
        sources,
        key=lambda source: (severity.get(source["readiness_state"], len(severity)), source["source_name"].lower()),
    )


def sort_source_tables(tables: list[SourceTableStatus]) -> list[SourceTableStatus]:
    """Most severe first, then alphabetically by source and table.

    Used for the per-source schema detail list, where a source can still have dozens of tables
    even after rolling sources up for the summary card — the one that's stalled should be first.
    """
    severity = {state: rank for rank, state in enumerate(READINESS_PRIORITY)}
    return sorted(
        tables,
        key=lambda table: (
            severity.get(table["readiness_state"], len(severity)),
            table["source_name"].lower(),
            table["table_name"].lower(),
        ),
    )


def _sources_status(team_id: int, *, user_access_control: UserAccessControl) -> SourcesStatus:
    tables = _schema_table_statuses(team_id, user_access_control=user_access_control)
    if not tables:
        return {
            "readiness_state": "not_configured",
            "detail": "No imported source tables are configured for this warehouse.",
            "sources": [],
        }

    sources = _rollup_sources(tables)
    readiness_state = _roll_up_state([source["readiness_state"] for source in sources])
    details: dict[ReadinessState, str] = {
        "needs_attention": "One or more imported sources need attention.",
        "backfilling": "A copy or register workflow is running for one or more imported sources.",
        "waiting": "One or more imported sources are waiting to start.",
        "sync_paused": "Sync is paused for one or more imported sources.",
        "up_to_date": "All imported sources are up to date.",
        "not_configured": "No imported source tables are configured for this warehouse.",
    }
    return {"readiness_state": readiness_state, "detail": details[readiness_state], "sources": sources}


def _roll_up_state(states: list[ReadinessState]) -> ReadinessState:
    for candidate in READINESS_PRIORITY:
        if candidate in states:
            return candidate
    return "not_configured"


def get_managed_warehouse_data_status(
    team_id: int, *, user_access_control: UserAccessControl
) -> ManagedWarehouseDataStatus:
    # A status read degrades to None (reported not_configured) when the control plane
    # can't answer; it must never 500.
    backfill = team_backfill_membership(team_id)
    partitions = list(
        ManagedWarehouseBackfillPartition.objects.for_team(team_id)
        .filter(environment_id=team_id)
        .order_by("-updated_at")
    )
    events = dataset_status(
        dataset="events",
        backfill=backfill,
        partitions=[row for row in partitions if row.dataset == ManagedWarehouseBackfillPartition.Dataset.EVENTS],
    )
    persons = dataset_status(
        dataset="persons",
        backfill=backfill,
        partitions=[row for row in partitions if row.dataset == ManagedWarehouseBackfillPartition.Dataset.PERSONS],
    )
    sources = _sources_status(team_id, user_access_control=user_access_control)
    return {
        "overall_readiness_state": _roll_up_state(
            [events["readiness_state"], persons["readiness_state"], sources["readiness_state"]]
        ),
        "events": events,
        "persons": persons,
        "sources": sources,
        "generated_at": timezone.now(),
    }


def _project_timezone(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")
    except Exception:
        return ZoneInfo("UTC")


def get_managed_warehouse_landing_history(
    team_id: int, *, days: int, timezone_name: str | None, user_access_control: UserAccessControl
) -> LandingHistory:
    """Per-day counts of finished warehouse source attempts and backfill partitions, oldest day first."""
    tz = _project_timezone(timezone_name)
    today = datetime.now(tz).date()
    first_day = today - timedelta(days=days - 1)
    start = datetime.combine(first_day, time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)

    source_counts: dict[date, tuple[int, int]] = {}
    schema_ids = list(
        _visible_schemas_queryset(team_id, user_access_control=user_access_control).values_list("id", flat=True)
    )
    for count in source_jobs.count_finished_source_jobs_by_day(
        team_id=team_id, schema_ids=schema_ids, start=start, end=end, tz=tz
    ):
        source_counts[count.day] = (count.completed, count.failed)

    lifecycle = ManagedWarehouseBackfillPartition.LifecycleState
    partition_rows = (
        ManagedWarehouseBackfillPartition.objects.for_team(team_id)
        .filter(
            environment_id=team_id,
            dataset__in=[
                ManagedWarehouseBackfillPartition.Dataset.EVENTS,
                ManagedWarehouseBackfillPartition.Dataset.PERSONS,
            ],
            lifecycle_state__in=[lifecycle.COMPLETED, lifecycle.FAILED],
            completed_at__gte=start,
            completed_at__lt=end,
        )
        .annotate(day=TruncDate("completed_at", tzinfo=tz))
        .values("day")
        .annotate(
            succeeded=Count("id", filter=Q(lifecycle_state=lifecycle.COMPLETED)),
            failed=Count("id", filter=Q(lifecycle_state=lifecycle.FAILED)),
        )
        .order_by("day")
    )
    backfill_counts = {row["day"]: (row["succeeded"], row["failed"]) for row in partition_rows}

    buckets = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        source_succeeded, source_failed = source_counts.get(day, (0, 0))
        backfill_succeeded, backfill_failed = backfill_counts.get(day, (0, 0))
        buckets.append(
            LandingHistoryBucket(
                date=day,
                source_succeeded=source_succeeded,
                source_failed=source_failed,
                backfill_succeeded=backfill_succeeded,
                backfill_failed=backfill_failed,
            )
        )
    return LandingHistory(days=days, buckets=buckets)
