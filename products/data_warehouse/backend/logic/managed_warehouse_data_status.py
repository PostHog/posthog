from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, TypedDict

from django.db import DatabaseError
from django.db.models import Count, Exists, Max, Min, OuterRef, Q, Subquery
from django.utils import timezone

import structlog

from posthog.ducklake.models import DuckgresServerTeam, DuckgresSinkSchemaState

from products.data_warehouse.backend.logic.backfill_status import historical_backfill_months
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources_queue.backend.models import (
    SourceBatch,
    SourceBatchDuckgresApply,
    SourceBatchDuckgresStatus,
)

logger = structlog.get_logger(__name__)

ReadinessState = Literal[
    "not_configured",
    "waiting",
    "backfilling",
    "catching_up",
    "up_to_date",
    "needs_attention",
    "unknown",
    "sync_paused",
]

QUEUE_RETENTION_DAYS = 14
PERSISTENT_BACKFILL_FAILURES = 3
# sync_paused ranks below every active-work or failure state (those are still worth surfacing even
# on a paused schema's source) but above up_to_date: a source with some schemas paused shouldn't
# read as fully "up to date" when part of it isn't being kept current at all.
READINESS_PRIORITY: tuple[ReadinessState, ...] = (
    "needs_attention",
    "backfilling",
    "catching_up",
    "waiting",
    "unknown",
    "sync_paused",
    "up_to_date",
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
    # Whether the one-time historical copy into the warehouse has completed (sink state PRIMED).
    # Independent of readiness_state, which also folds in live-catchup and failure signals.
    backfilled: bool
    completed_chunks: int
    total_chunks: int | None
    pending_batches: int | None
    oldest_pending_at: datetime | None
    last_applied_at: datetime | None
    last_synced_at: datetime | None


class SourceSummary(TypedDict):
    source_id: str
    source_name: str
    source_type: str
    readiness_state: ReadinessState
    detail: str
    total_schemas: int
    backfilled_schemas: int
    pending_batches: int | None
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


class QueueTailStatus(TypedDict):
    pending_batches: int
    oldest_pending_at: datetime | None
    last_applied_at: datetime | None


def _event_historical_partition_count(backfill: DuckgresServerTeam) -> int | None:
    if backfill.earliest_event_date is None:
        return None

    # Same helper the scheduler enqueues from, so this denominator always matches what actually runs.
    return len(historical_backfill_months(backfill.earliest_event_date))


def dataset_status(
    *,
    dataset: Literal["events", "persons"],
    backfill: DuckgresServerTeam | None,
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


def _queue_tail_statuses(team_id: int, schema_ids: list[str]) -> dict[str, QueueTailStatus] | None:
    if not schema_ids:
        return {}

    try:
        queue_cutoff = timezone.now() - timedelta(days=QUEUE_RETENTION_DAYS)
        latest_duckgres_state = Subquery(
            SourceBatchDuckgresStatus.objects.filter(
                batch_id=OuterRef("pk"),
                created_at__gte=queue_cutoff - timedelta(days=QUEUE_RETENTION_DAYS),
            )
            .order_by("-created_at", "-id")
            .values("job_state")[:1]
        )
        has_apply = Exists(
            SourceBatchDuckgresApply.objects.for_team(team_id).filter(
                schema_id=OuterRef("schema_id"),
                run_uuid=OuterRef("run_uuid"),
                batch_index=OuterRef("batch_index"),
            )
        )
        pending_rows = (
            SourceBatch.objects.filter(
                team_id=team_id,
                schema_id__in=schema_ids,
                latest_state=SourceBatch.LatestState.SUCCEEDED,
                is_final_batch=False,
                created_at__gte=queue_cutoff,
            )
            .annotate(latest_duckgres_state=latest_duckgres_state, has_apply=has_apply)
            .filter(has_apply=False)
            .filter(
                Q(latest_duckgres_state__isnull=True)
                | Q(
                    latest_duckgres_state__in=[
                        SourceBatchDuckgresStatus.State.EXECUTING,
                        SourceBatchDuckgresStatus.State.WAITING_RETRY,
                    ]
                )
            )
            .values("schema_id")
            .annotate(pending_batches=Count("id"), oldest_pending_at=Min("created_at"))
        )
        applied_rows = (
            SourceBatchDuckgresApply.objects.for_team(team_id)
            .filter(schema_id__in=schema_ids, created_at__gte=queue_cutoff)
            .values("schema_id")
            .annotate(last_applied_at=Max("created_at"))
        )
        statuses: dict[str, QueueTailStatus] = {
            schema_id: {
                "pending_batches": 0,
                "oldest_pending_at": None,
                "last_applied_at": None,
            }
            for schema_id in schema_ids
        }
        for row in pending_rows:
            schema_id = str(row["schema_id"])
            statuses[schema_id]["pending_batches"] = int(row["pending_batches"])
            statuses[schema_id]["oldest_pending_at"] = row["oldest_pending_at"]
        for row in applied_rows:
            statuses[str(row["schema_id"])]["last_applied_at"] = row["last_applied_at"]
        return statuses
    except DatabaseError:
        logger.exception("managed_warehouse_queue_status_unavailable", team_id=team_id)
        return None


def source_table_readiness(
    state: DuckgresSinkSchemaState, queue_status: QueueTailStatus | None, queue_available: bool
) -> tuple[ReadinessState, str]:
    if (
        state.state == DuckgresSinkSchemaState.State.NEEDS_RESYNC
        or state.consecutive_failures >= PERSISTENT_BACKFILL_FAILURES
    ):
        return "needs_attention", "This table needs a fresh warehouse copy before imports can continue."
    if state.state == DuckgresSinkSchemaState.State.PENDING_BACKFILL:
        return "waiting", "Waiting to copy existing rows into the warehouse."
    if state.state == DuckgresSinkSchemaState.State.BACKFILLING:
        if state.chunk_count:
            return "backfilling", f"Copied {state.chunks_applied} of {state.chunk_count} backfill chunks."
        return "backfilling", "Existing rows are being copied into the warehouse."
    if not queue_available:
        return "unknown", "Live import status is temporarily unavailable."
    if queue_status and queue_status["pending_batches"] > 0:
        count = queue_status["pending_batches"]
        suffix = "batch" if count == 1 else "batches"
        return "catching_up", f"Applying {count} imported {suffix} to the warehouse."
    return "up_to_date", "Imported data is up to date."


def _schema_table_statuses(team_id: int, *, source_id: str | None = None) -> list[SourceTableStatus]:
    """Per-schema readiness, optionally scoped to one source.

    Shared by the top-level rollup (all sources, for the Overview tab's summary card) and the
    per-source detail lookup (one source's schemas, for the drill-down modal) so the readiness
    computation and the visibility rules never drift between the two views.
    """
    states = list(DuckgresSinkSchemaState.objects.filter(team_id=team_id).order_by("schema_id"))
    if not states:
        return []

    # should_sync is deliberately not filtered here: a schema with sync paused still has real,
    # queryable data in the warehouse (or a genuine backfill-in-progress state), and hiding it
    # entirely reads as "nothing here" rather than "this one isn't actively syncing right now".
    # Only schemas/sources that no longer exist (soft-deleted) are excluded.
    schema_filter: dict[str, object] = {
        "team_id": team_id,
        "id__in": [state.schema_id for state in states],
        "deleted": False,
        "source__deleted": False,
    }
    if source_id is not None:
        schema_filter["source_id"] = source_id

    schema_by_id = {
        str(schema.id): schema for schema in ExternalDataSchema.objects.filter(**schema_filter).select_related("source")
    }
    visible_states = [state for state in states if str(state.schema_id) in schema_by_id]
    schema_ids = [str(state.schema_id) for state in visible_states]
    queue_statuses = _queue_tail_statuses(team_id, schema_ids)
    queue_available = queue_statuses is not None

    tables: list[SourceTableStatus] = []
    for state in visible_states:
        schema_id = str(state.schema_id)
        schema = schema_by_id[schema_id]
        queue_status = queue_statuses.get(schema_id) if queue_statuses is not None else None
        if schema.should_sync:
            readiness_state, detail = source_table_readiness(state, queue_status, queue_available)
        else:
            # Paused wins over whatever the sink state says: a stale failure streak from before
            # the pause isn't actionable while nothing is actively importing for this table.
            readiness_state, detail = (
                "sync_paused",
                "Sync is paused for this table. Data already in the warehouse is unaffected.",
            )
        tables.append(
            {
                "schema_id": schema_id,
                "source_id": str(schema.source_id),
                "source_name": schema.source.prefix or schema.source.source_type,
                "source_type": schema.source.source_type,
                "table_name": schema.name,
                "readiness_state": readiness_state,
                "detail": detail,
                "backfilled": state.state == DuckgresSinkSchemaState.State.PRIMED,
                "completed_chunks": state.chunks_applied,
                "total_chunks": state.chunk_count,
                "pending_batches": queue_status["pending_batches"] if queue_status is not None else None,
                "oldest_pending_at": queue_status["oldest_pending_at"] if queue_status is not None else None,
                "last_applied_at": queue_status["last_applied_at"] if queue_status is not None else None,
                "last_synced_at": schema.last_synced_at,
            }
        )
    return tables


def get_source_schema_statuses(team_id: int, source_id: str) -> list[SourceTableStatus]:
    """Per-schema detail for one imported source — backs the Overview tab's drill-down modal."""
    return sort_source_tables(_schema_table_statuses(team_id, source_id=source_id))


_SOURCE_SUMMARY_DETAILS: dict[ReadinessState, str] = {
    "needs_attention": "One or more schemas need attention.",
    "backfilling": "Historical rows are being copied for one or more schemas.",
    "catching_up": "Recent imports are still being applied for one or more schemas.",
    "waiting": "One or more schemas are waiting to start.",
    "unknown": "Live import status is temporarily unavailable for one or more schemas.",
    "sync_paused": "Sync is paused for one or more schemas.",
    "up_to_date": "All schemas are up to date.",
    "not_configured": "No schemas are configured for this source.",
}


def _rollup_sources(tables: list[SourceTableStatus]) -> list[SourceSummary]:
    grouped: dict[str, list[SourceTableStatus]] = {}
    for table in tables:
        grouped.setdefault(table["source_id"], []).append(table)

    summaries: list[SourceSummary] = []
    for source_id, rows in grouped.items():
        readiness_state = _roll_up_state([row["readiness_state"] for row in rows])
        # pending_batches is uniformly None (queue check failed) or uniformly an int across a
        # team's rows, since _queue_tail_statuses either fails for all schemas or none.
        pending_batches = (
            None if rows[0]["pending_batches"] is None else sum(row["pending_batches"] or 0 for row in rows)
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
                "backfilled_schemas": sum(1 for row in rows if row["backfilled"]),
                "pending_batches": pending_batches,
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


def _sources_status(team_id: int) -> SourcesStatus:
    tables = _schema_table_statuses(team_id)
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
        "backfilling": "Existing rows are being copied for one or more imported sources.",
        "catching_up": "Recent imports are still being applied to the warehouse.",
        "waiting": "One or more imported sources are waiting to start.",
        "unknown": "Some live import statuses are temporarily unavailable.",
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


def get_managed_warehouse_data_status(team_id: int) -> ManagedWarehouseDataStatus:
    backfill = DuckgresServerTeam.objects.filter(team_id=team_id).first()
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
    sources = _sources_status(team_id)
    return {
        "overall_readiness_state": _roll_up_state(
            [events["readiness_state"], persons["readiness_state"], sources["readiness_state"]]
        ),
        "events": events,
        "persons": persons,
        "sources": sources,
        "generated_at": timezone.now(),
    }
