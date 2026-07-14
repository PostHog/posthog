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
]

QUEUE_RETENTION_DAYS = 14
PERSISTENT_BACKFILL_FAILURES = 3
READINESS_PRIORITY: tuple[ReadinessState, ...] = (
    "needs_attention",
    "backfilling",
    "catching_up",
    "waiting",
    "unknown",
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
    completed_chunks: int
    total_chunks: int | None
    pending_batches: int | None
    oldest_pending_at: datetime | None
    last_applied_at: datetime | None
    last_synced_at: datetime | None


class SourcesStatus(TypedDict):
    readiness_state: ReadinessState
    detail: str
    tables: list[SourceTableStatus]


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


def _sources_status(team_id: int) -> SourcesStatus:
    states = list(DuckgresSinkSchemaState.objects.filter(team_id=team_id).order_by("schema_id"))
    if not states:
        return {
            "readiness_state": "not_configured",
            "detail": "No imported source tables are configured for this warehouse.",
            "tables": [],
        }

    schema_by_id = {
        str(schema.id): schema
        for schema in ExternalDataSchema.objects.filter(
            team_id=team_id,
            id__in=[state.schema_id for state in states],
            should_sync=True,
            deleted=False,
            source__deleted=False,
        ).select_related("source")
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
        readiness_state, detail = source_table_readiness(state, queue_status, queue_available)
        tables.append(
            {
                "schema_id": schema_id,
                "source_id": str(schema.source_id),
                "source_name": schema.source.prefix or schema.source.source_type,
                "source_type": schema.source.source_type,
                "table_name": schema.name,
                "readiness_state": readiness_state,
                "detail": detail,
                "completed_chunks": state.chunks_applied,
                "total_chunks": state.chunk_count,
                "pending_batches": queue_status["pending_batches"] if queue_status is not None else None,
                "oldest_pending_at": queue_status["oldest_pending_at"] if queue_status is not None else None,
                "last_applied_at": queue_status["last_applied_at"] if queue_status is not None else None,
                "last_synced_at": schema.last_synced_at,
            }
        )

    if not tables:
        return {
            "readiness_state": "not_configured",
            "detail": "No imported source tables are configured for this warehouse.",
            "tables": [],
        }

    tables = sort_source_tables(tables)
    readiness_state = _roll_up_state([table["readiness_state"] for table in tables])
    details: dict[ReadinessState, str] = {
        "needs_attention": "One or more imported tables need attention.",
        "backfilling": "Existing rows are being copied for one or more imported tables.",
        "catching_up": "Recent imports are still being applied to the warehouse.",
        "waiting": "One or more imported tables are waiting to start.",
        "unknown": "Some live import statuses are temporarily unavailable.",
        "up_to_date": "All imported source tables are up to date.",
        "not_configured": "No imported source tables are configured for this warehouse.",
    }
    return {"readiness_state": readiness_state, "detail": details[readiness_state], "tables": tables}


def sort_source_tables(tables: list[SourceTableStatus]) -> list[SourceTableStatus]:
    """Most severe first, then alphabetically by source and table.

    A team can import dozens of tables and the UI paginates at 20, so the one table that has
    stalled has to land on the first page. Ordering by schema_id (a UUID) scattered it.
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
