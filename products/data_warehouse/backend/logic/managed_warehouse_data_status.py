from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from django.utils import timezone

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
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceAccessMethod

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

    return {
        "dataset": dataset,
        "readiness_state": readiness_state,
        "detail": detail,
        "completed_partitions": completed_partitions,
        "total_partitions": total_partitions,
        "current_partition": current_partition,
        "last_updated_at": last_updated_at,
    }


def source_table_readiness(state: ManagedWarehouseSourceJobRecord | None) -> tuple[ReadinessState, str]:
    if state is None:
        return "waiting", "Waiting for a copy or register workflow to run."

    workflow_name = state.workflow_type.value
    if state.status == ManagedWarehouseSourceJobStatus.FAILED:
        return "needs_attention", f"The latest {workflow_name} workflow failed. Retry the source sync."
    if state.status == ManagedWarehouseSourceJobStatus.RUNNING:
        return "backfilling", f"The {workflow_name} workflow is applying the latest source import."
    if state.status == ManagedWarehouseSourceJobStatus.COMPLETED:
        return "up_to_date", "The latest source import was applied."
    if state.status == ManagedWarehouseSourceJobStatus.STALE:
        return "waiting", "A newer source import replaced this register workflow."
    return "waiting", f"The {workflow_name} workflow did not apply this source import."


def _schema_table_statuses(
    team_id: int, *, user_access_control: UserAccessControl, source_id: str | None = None
) -> list[SourceTableStatus]:
    """Per-schema readiness, optionally scoped to one source.

    Shared by the top-level rollup (all sources, for the Overview tab's summary card) and the
    per-source detail lookup (one source's schemas, for the drill-down modal) so the readiness
    computation and the visibility rules never drift between the two views.
    """
    source_filter: dict[str, object] = {
        "team_id": team_id,
        "deleted": False,
        "access_method": ExternalDataSourceAccessMethod.WAREHOUSE,
    }
    if source_id is not None:
        source_filter["id"] = source_id
    sources = user_access_control.filter_queryset_by_access_level(ExternalDataSource.objects.filter(**source_filter))

    schema_filter: dict[str, object] = {
        "team_id": team_id,
        "deleted": False,
        "source__in": sources,
    }

    schemas = list(ExternalDataSchema.objects.filter(**schema_filter).select_related("source"))
    latest_jobs_by_schema = {
        state.schema_id: state
        for state in source_jobs.list_latest_source_jobs(team_id=team_id, schema_ids=[schema.id for schema in schemas])
    }

    tables: list[SourceTableStatus] = []
    for schema in schemas:
        state = latest_jobs_by_schema.get(schema.id)
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
        summaries.append(
            {
                "source_id": source_id,
                "source_name": rows[0]["source_name"],
                "source_type": rows[0]["source_type"],
                "readiness_state": readiness_state,
                "detail": _SOURCE_SUMMARY_DETAILS[readiness_state],
                "total_schemas": len(rows),
                "applied_schemas": sum(1 for row in rows if row["applied"]),
                "last_applied_at": last_applied_at,
                "last_synced_at": last_synced_at,
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
