from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from django.db import DatabaseError
from django.utils import timezone

import structlog

from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition

logger = structlog.get_logger(__name__)

Granularity = ManagedWarehouseBackfillPartition.Granularity
LifecycleState = ManagedWarehouseBackfillPartition.LifecycleState

# Partition key shapes. These are PostHog's convention for naming a unit of backfill work, not
# any one scheduler's: `1_2026-05` (a historical month), `1_2026-05-04` (a day), `1` (persons'
# whole history in one run). This module is the only place that decodes them.
_FULL_KEY = re.compile(r"^\d+$")
_MONTH_KEY = re.compile(r"^\d+_(?P<year>\d{4})-(?P<month>\d{2})$")
_DAY_KEY = re.compile(r"^\d+_(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

# How long a row may sit in RUNNING before the repair sweep asks the scheduler whether its run
# is actually still alive. Only a cost gate — a run that legitimately outlives it is left alone.
STALE_RUNNING_AGE = timedelta(hours=1)


class BackfillOutcome(StrEnum):
    """How a backfill run ended, in terms the product understands.

    Schedulers report completion in their own vocabulary (Dagster has DagsterRunStatus, the next
    one will have something else). Callers map into this enum at the boundary so nothing below
    this line depends on which scheduler runs the job.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class PartitionDescriptor:
    granularity: str
    period_start: date | None


def describe_partition_key(partition_key: str) -> PartitionDescriptor:
    """Decode a partition key into the period it covers. Raises ValueError on an unknown shape."""
    if _FULL_KEY.fullmatch(partition_key):
        return PartitionDescriptor(granularity=Granularity.FULL, period_start=None)

    day = _DAY_KEY.fullmatch(partition_key)
    if day:
        return PartitionDescriptor(
            granularity=Granularity.DAY,
            period_start=date(int(day["year"]), int(day["month"]), int(day["day"])),
        )

    month = _MONTH_KEY.fullmatch(partition_key)
    if month:
        return PartitionDescriptor(
            granularity=Granularity.MONTH,
            period_start=date(int(month["year"]), int(month["month"]), 1),
        )

    raise ValueError(f"Unrecognized backfill partition key: {partition_key!r}")


def get_months_in_range(start_date: date, end_date: date) -> list[str]:
    """Generate list of month strings (YYYY-MM) between start and end dates."""
    months = []
    current = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while current <= end_month:
        months.append(current.strftime("%Y-%m"))
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


def historical_backfill_months(earliest_event_date: date, *, today: date | None = None) -> list[str]:
    """Complete months the events backfill is expected to cover.

    The current, in-progress month belongs to the daily backfill, so history stops at the end of
    last month. Both the scheduler (which enqueues these months) and the readiness endpoint (which
    counts them) call this, so the numerator and the denominator can't drift apart.
    """
    today = today or timezone.now().date()
    last_complete_month = today.replace(day=1) - timedelta(days=1)
    if earliest_event_date > last_complete_month:
        return []
    return get_months_in_range(earliest_event_date, last_complete_month)


def record_backfill_started(*, team_id: int, dataset: str, partition_key: str, run_id: str) -> None:
    """Record that a partition is being backfilled. Safe to call again for a retry of the same partition."""
    try:
        descriptor = describe_partition_key(partition_key)
        ManagedWarehouseBackfillPartition.objects.for_team(team_id).update_or_create(
            environment_id=team_id,
            dataset=dataset,
            partition_key=partition_key,
            defaults={
                "team_id": team_id,
                "granularity": descriptor.granularity,
                "period_start": descriptor.period_start,
                "lifecycle_state": LifecycleState.RUNNING,
                "run_id": run_id,
                "started_at": timezone.now(),
                "completed_at": None,
                "last_error": None,
            },
        )
    except (DatabaseError, ValueError):
        # Status is a projection for the UI: never fail the backfill itself over it.
        logger.exception(
            "managed_warehouse_backfill_status_write_failed",
            team_id=team_id,
            dataset=dataset,
            partition_key=partition_key,
        )


def record_backfill_finished(
    *,
    team_id: int,
    dataset: str,
    partition_key: str,
    run_id: str,
    error: Exception | None = None,
    failure_reason: str | None = None,
) -> None:
    """Record that a partition finished, successfully or not.

    Pass `error` when the recording process caught the failure itself; pass `failure_reason`
    when the failure is known only second-hand (a repaired crash, a lost run).
    """
    _finish(
        team_id=team_id,
        dataset=dataset,
        partition_key=partition_key,
        run_id=run_id,
        failure_reason=type(error).__name__[:128] if error is not None else failure_reason,
    )


def record_backfill_outcome(
    *,
    team_id: int,
    dataset: str,
    partition_key: str,
    run_id: str,
    outcome: BackfillOutcome,
    failure_reason: str = "RunDidNotComplete",
) -> None:
    """Project a run this process never saw onto the partition row.

    Used when reconstructing status from a scheduler's own run history, where all we know is how
    the run ended.
    """
    record_backfill_started(team_id=team_id, dataset=dataset, partition_key=partition_key, run_id=run_id)
    if outcome is BackfillOutcome.SUCCEEDED:
        _finish(team_id=team_id, dataset=dataset, partition_key=partition_key, run_id=run_id, failure_reason=None)
    elif outcome is BackfillOutcome.FAILED:
        _finish(
            team_id=team_id,
            dataset=dataset,
            partition_key=partition_key,
            run_id=run_id,
            failure_reason=failure_reason,
        )


def stale_running_partitions(*, dataset: str, limit: int) -> list[ManagedWarehouseBackfillPartition]:
    """Rows stuck in RUNNING long enough that the recording process may have died mid-run.

    A process killed between record_backfill_started and record_backfill_finished (OOM, pod
    eviction) never writes its terminal state, so without repair the row reports "backfilling"
    forever. The scheduler resolves these against its own run records; the age gate only avoids
    churning on rows whose run is plausibly still in flight.
    """
    cutoff = timezone.now() - STALE_RUNNING_AGE
    try:
        return list(
            # unscoped: repair sweeps all teams from a scheduler context, not one tenant.
            ManagedWarehouseBackfillPartition.objects.unscoped()
            .filter(dataset=dataset, lifecycle_state=LifecycleState.RUNNING, updated_at__lt=cutoff)
            .order_by("updated_at")[:limit]
        )
    except DatabaseError:
        logger.exception("managed_warehouse_backfill_stale_running_query_failed", dataset=dataset)
        return []


def _finish(*, team_id: int, dataset: str, partition_key: str, run_id: str, failure_reason: str | None) -> None:
    updates: dict[str, object] = {
        "run_id": run_id,
        "completed_at": timezone.now(),
        "lifecycle_state": LifecycleState.COMPLETED if failure_reason is None else LifecycleState.FAILED,
        "last_error": failure_reason,
    }
    try:
        ManagedWarehouseBackfillPartition.objects.for_team(team_id).filter(
            environment_id=team_id,
            dataset=dataset,
            partition_key=partition_key,
        ).update(**updates)
    except DatabaseError:
        logger.exception(
            "managed_warehouse_backfill_status_write_failed",
            team_id=team_id,
            dataset=dataset,
            partition_key=partition_key,
        )
