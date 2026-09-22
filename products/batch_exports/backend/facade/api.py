"""
Facade for batch_exports.

Capability-oriented functions that take and return the framework-free contracts in
``facade/contracts.py``. The facade never hands an ORM instance across the boundary, and
every read is scoped by ``team_id``. Mappers are explicit, so the shape a consumer sees
is visible in one place.

``service.py`` imports ``temporalio`` at module scope, and the startup import budget
(``posthog/test/repo_invariants/test_startup_import_budget.py``) forbids both that module
and ``temporalio`` on the ``django.setup()`` path. Core config-time consumers import this
facade, so it reaches the service only through ``_service()``, which imports it at call
time. For the same reason the Temporal client is built in ``_get_temporal_client()``.

Temporal workflow and activity registration crosses as objects, not data, so it lives in
``facade/temporal.py``; the pipeline internals the warehouse writers reuse live in
``facade/pipeline.py``. Neither may be imported from here.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

import structlog

from products.batch_exports.backend.billing import exclude_non_billable_runs
from products.batch_exports.backend.models.batch_export import (
    BATCH_EXPORT_INTERVALS,
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
    get_batch_exports_using_integration,
)

from . import contracts

if TYPE_CHECKING:
    from temporalio.client import Client

__all__ = [
    "MultipleBatchExportsError",
    "backfill_batch_export",
    "count_batch_exports_for_teams",
    "create_batch_export",
    "delete_batch_export",
    "delete_batch_exports_for_teams",
    "get_backfill_for_export",
    "get_batch_export_by_name",
    "get_latest_completed_run",
    "get_latest_run",
    "get_run_failure",
    "get_teams_with_active_batch_exports",
    "get_teams_with_billable_rows_exported",
    "list_batch_exports_using_integration",
    "list_latest_failed_runs",
    "list_supported_intervals",
]

logger = structlog.get_logger(__name__)

# The statuses that make the latest run of an export an actionable failure.
FAILED_RUN_STATUSES = (
    BatchExportRun.Status.FAILED,
    BatchExportRun.Status.FAILED_RETRYABLE,
    BatchExportRun.Status.TIMEDOUT,
    BatchExportRun.Status.TERMINATED,
)

# An on-demand export has no name of its own, so a failure list labels it generically.
ON_DEMAND_EXPORT_NAME = "On-demand batch export"


class MultipleBatchExportsError(Exception):
    """Raised when a lookup that expects at most one batch export matches several."""


def _service() -> ModuleType:
    """Import the service layer at call time. See the module docstring for why."""
    from products.batch_exports.backend import service

    return service


def _get_temporal_client() -> "Client":
    """Connect to Temporal at call time. See the module docstring for why."""
    from posthog.temporal.common.client import sync_connect

    return sync_connect()


def _to_ref(batch_export: BatchExport) -> contracts.BatchExportRef:
    return contracts.BatchExportRef(id=batch_export.id, name=batch_export.name)


def _to_detail(batch_export: BatchExport) -> contracts.BatchExportDetail:
    # The destination config is an encrypted field, so reading it decrypts the destination's
    # credentials. Only the two event filters are lifted out of it, which is all any consumer reads.
    # Do not widen this to the whole config unless we are certain all credentials have been migrated
    # to integrations and dropped from the config.
    config = batch_export.destination.config
    return contracts.BatchExportDetail(
        id=batch_export.id,
        team_id=batch_export.team_id,
        name=batch_export.name,
        interval=batch_export.interval,
        paused=batch_export.paused,
        created_at=batch_export.created_at,
        last_updated_at=batch_export.last_updated_at,
        destination_type=batch_export.destination.type,
        # A stored filter can be null, not only absent, so the fallback covers both.
        exclude_events=tuple(config.get("exclude_events") or ()),
        include_events=tuple(config.get("include_events") or ()),
    )


def _to_backfill_summary(backfill: BatchExportBackfill) -> contracts.BatchExportBackfillSummary:
    return contracts.BatchExportBackfillSummary(
        id=backfill.id,
        status=backfill.status,
        start_at=backfill.start_at,
        adjusted_start_at=backfill.adjusted_start_at,
        created_at=backfill.created_at,
        last_updated_at=backfill.last_updated_at,
    )


def _to_run_summary(run: BatchExportRun) -> contracts.BatchExportRunSummary:
    return contracts.BatchExportRunSummary(
        id=run.id,
        status=run.status,
        latest_error=run.latest_error,
        data_interval_start=run.data_interval_start,
        data_interval_end=run.data_interval_end,
        finished_at=run.finished_at,
        created_at=run.created_at,
        last_updated_at=run.last_updated_at,
    )


def list_batch_exports_using_integration(team_id: int, integration_id: int) -> list[contracts.BatchExportRef]:
    """Return the live batch exports that write through this integration."""
    return [_to_ref(batch_export) for batch_export in get_batch_exports_using_integration(team_id, integration_id)]


def count_batch_exports_for_teams(team_ids: Sequence[int]) -> int:
    """Count the batch exports these teams have, not counting deleted ones."""
    return BatchExport.objects.filter(team_id__in=team_ids, deleted=False).count()


def list_latest_failed_runs(team_id: int) -> list[contracts.FailedBatchExportRun]:
    """Return the exports whose most recent run failed.

    Only the latest run of each export counts, so an export that has recovered does not
    appear. A paused export is left out too: its last failure is no longer actionable.
    """
    latest_run_ids = (
        BatchExportRun.objects.filter(
            batch_export__team_id=team_id,
            batch_export__deleted=False,
            batch_export__paused=False,
        )
        .order_by("batch_export_id", "-created_at")
        .distinct("batch_export_id")
        .values_list("id", flat=True)
    )

    # nosemgrep: idor-lookup-without-team (IDs from team-scoped queryset)
    failed_runs = BatchExportRun.objects.filter(id__in=latest_run_ids, status__in=FAILED_RUN_STATUSES).select_related(
        "batch_export"
    )

    return [
        contracts.FailedBatchExportRun(
            export_id=run.parent.id,
            export_name=getattr(run.parent, "name", ON_DEMAND_EXPORT_NAME),
            error=run.latest_error,
            failed_at=run.finished_at,
        )
        for run in failed_runs
    ]


def get_run_failure(run_id: UUID | str, team_id: int) -> contracts.BatchExportRunFailure | None:
    """Return a failed run with the export and team that own it, or None for an on-demand run.

    An on-demand export has no page of its own, so there is nothing to point a person at.
    The team is matched against either parent, so an on-demand run still resolves and
    returns None rather than raising.
    """
    run = BatchExportRun.objects.select_related("batch_export", "batch_export_on_demand").get(
        Q(batch_export__team_id=team_id) | Q(batch_export_on_demand__team_id=team_id),
        id=run_id,
    )
    export = run.parent

    if not isinstance(export, BatchExport):
        return None

    return contracts.BatchExportRunFailure(
        run_id=run.id,
        team_id=export.team_id,
        export_id=export.id,
        export_name=export.name,
        last_updated_at=run.last_updated_at,
    )


def get_teams_with_billable_rows_exported(begin: dt.datetime, end: dt.datetime) -> list[contracts.TeamTotal]:
    """Sum the rows each team exported through billable runs that finished in the period."""
    completed_runs = BatchExportRun.objects.filter(
        finished_at__gte=begin,
        finished_at__lte=end,
        status=BatchExportRun.Status.COMPLETED,
    )
    rows = (
        exclude_non_billable_runs(completed_runs)
        .values(team_id=Coalesce(F("batch_export__team_id"), F("batch_export_on_demand__team_id")))
        # A run that recorded no count leaves records_completed null, so a team whose runs are
        # all null would sum to null. Coalesce keeps every total an integer.
        .annotate(total=Coalesce(Sum("records_completed"), 0))
    )
    return [contracts.TeamTotal(team_id=row["team_id"], total=row["total"]) for row in rows]


def get_teams_with_active_batch_exports() -> list[contracts.TeamTotal]:
    """Count the batch exports each team currently runs on a schedule.

    Deleted exports are excluded, which the usage report query this replaces does not do.
    Deletion never leaves an export paused - `service.delete_batch_export` saves a stale
    instance over the paused flag - so that query counts every export a team has ever
    deleted, and the number only ever grows. It drops once the usage report moves here.
    """
    rows = BatchExport.objects.filter(paused=False, deleted=False).values("team_id").annotate(total=Count("id"))
    return [contracts.TeamTotal(team_id=row["team_id"], total=row["total"]) for row in rows]


def delete_batch_exports_for_teams(team_ids: Sequence[int]) -> None:
    """Delete the batch exports of deleted teams, and the Temporal schedules behind them.

    A CASCADE delete of the team would leave the schedules running, so each export is
    deleted with its destination and its schedule together.
    """
    service = _service()
    temporal = _get_temporal_client()

    for batch_export in BatchExport.objects.filter(team_id__in=team_ids, deleted=False):
        schedule_id = batch_export.id

        batch_export.delete()
        batch_export.destination.delete()

        try:
            service.batch_export_delete_schedule(temporal, str(schedule_id))
        except service.BatchExportServiceScheduleNotFound as e:
            logger.warning("Schedule not found during team deletion", schedule_id=e.schedule_id)


def get_batch_export_by_name(team_id: int, name: str, destination_type: str) -> contracts.BatchExportDetail | None:
    """Return the one live export with this name and destination, or None."""
    try:
        batch_export = BatchExport.objects.select_related("destination").get(
            team_id=team_id, name=name, destination__type=destination_type, deleted=False
        )
    except BatchExport.DoesNotExist:
        return None
    except BatchExport.MultipleObjectsReturned as e:
        raise MultipleBatchExportsError(
            f"Team {team_id} has more than one batch export named {name!r} to {destination_type!r}"
        ) from e

    return _to_detail(batch_export)


def get_backfill_for_export(export_id: UUID, team_id: int) -> contracts.BatchExportBackfillSummary | None:
    """Return the most recent backfill of an export, or None if it has never been backfilled."""
    backfill = (
        BatchExportBackfill.objects.filter(batch_export_id=export_id, team_id=team_id).order_by("-created_at").first()
    )
    return _to_backfill_summary(backfill) if backfill is not None else None


def get_latest_run(export_id: UUID, team_id: int) -> contracts.BatchExportRunSummary | None:
    """Return the most recently created run of an export, or None if it has never run."""
    run = (
        BatchExportRun.objects.filter(batch_export_id=export_id, batch_export__team_id=team_id)
        .order_by("-created_at")
        .first()
    )
    return _to_run_summary(run) if run is not None else None


def get_latest_completed_run(export_id: UUID, team_id: int) -> contracts.BatchExportRunSummary | None:
    """Return the run that finished most recently, of those that completed."""
    run = (
        BatchExportRun.objects.filter(
            batch_export_id=export_id,
            batch_export__team_id=team_id,
            status=BatchExportRun.Status.COMPLETED,
        )
        .order_by("-finished_at")
        .first()
    )
    return _to_run_summary(run) if run is not None else None


def create_batch_export(
    team_id: int,
    *,
    name: str,
    destination_type: str,
    destination_config: Mapping[str, object],
    interval: str,
    paused: bool = False,
    end_at: dt.datetime | None = None,
) -> contracts.BatchExportDetail:
    """Create a batch export, its destination, and the Temporal schedule that drives it."""
    service = _service()

    destination = BatchExportDestination(type=destination_type, config=dict(destination_config))
    batch_export = BatchExport(
        team_id=team_id,
        destination=destination,
        name=name,
        interval=interval,
        paused=paused,
        end_at=end_at,
    )

    # Schedule first, then the rows, which is the order every caller uses today. It trades one
    # failure for the other: a failed save leaves an orphaned schedule, where the reverse order
    # would leave a row pointing at no schedule. Neither is compensated yet.
    service.sync_batch_export(batch_export, created=True)

    with transaction.atomic():
        destination.save()
        batch_export.save()

    return _to_detail(batch_export)


def delete_batch_export(export_id: UUID, team_id: int) -> None:
    """Delete a batch export: pause it, cancel its work, then drop its Temporal schedule."""
    service = _service()
    batch_export = BatchExport.objects.select_related("destination").get(id=export_id, team_id=team_id)
    service.delete_batch_export(batch_export)


def backfill_batch_export(
    export_id: UUID, team_id: int, start_at: dt.datetime | None, end_at: dt.datetime | None
) -> str:
    """Start a backfill of an export over a date range, and return the backfill id.

    With no ``end_at`` the backfill runs until it catches up with realtime, then unpauses
    the export.
    """
    service = _service()
    return service.backfill_export(_get_temporal_client(), str(export_id), team_id, start_at, end_at)


def list_supported_intervals() -> tuple[str, ...]:
    """Return the intervals a batch export may be scheduled on."""
    return tuple(interval for interval, _ in BATCH_EXPORT_INTERVALS)
