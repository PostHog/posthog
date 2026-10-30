"""Runs of a scheduled batch export: list them, look one up, retry it or cancel it.

The facade reaches this module through a call-time import, because it imports the service layer
and the Temporal client, neither of which may load on the ``django.setup()`` path.
"""

from uuid import UUID

from django.db.models import QuerySet

import structlog

from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.facade import contracts
from products.batch_exports.backend.logic.pagination import select_page
from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.service import backfill_export, cancel_running_batch_export_run

LOGGER = structlog.get_logger(__name__)
_CANCELLABLE_STATUSES = (BatchExportRun.Status.RUNNING, BatchExportRun.Status.STARTING)


def to_run_detail(run: BatchExportRun) -> contracts.BatchExportRunDetail:
    return contracts.BatchExportRunDetail(
        id=run.id,
        status=run.status,
        records_completed=run.records_completed,
        records_failed=run.records_failed,
        latest_error=run.latest_error,
        data_interval_start=run.data_interval_start,
        data_interval_end=run.data_interval_end,
        cursor=run.cursor,
        created_at=run.created_at,
        finished_at=run.finished_at,
        last_updated_at=run.last_updated_at,
        records_total_count=run.records_total_count,
        bytes_exported=run.bytes_exported,
        batch_export_id=run.batch_export_id,
        batch_export_on_demand_id=run.batch_export_on_demand_id,
        backfill_id=run.backfill_id,
    )


def _query_export_runs(team_id: int, export_id: UUID) -> QuerySet[BatchExportRun]:
    return BatchExportRun.objects.filter(
        batch_export_id=export_id, batch_export__team_id=team_id, batch_export__deleted=False
    )


def _get_run(team_id: int, export_id: UUID, run_id: UUID) -> BatchExportRun:
    try:
        return _query_export_runs(team_id, export_id).select_related("batch_export").get(id=run_id)
    except BatchExportRun.DoesNotExist as e:
        raise contracts.BatchExportRunNotFoundError() from e


def list_runs(
    team_id: int, export_id: UUID, filters: contracts.BatchExportRunFilters, page: contracts.ListPage
) -> list[contracts.BatchExportRunDetail]:
    runs = _query_export_runs(team_id, export_id)
    if filters.created is not None:
        runs = runs.filter(created_at__range=(filters.created.start, filters.created.end))
    if filters.data_interval is not None:
        runs = runs.filter(
            data_interval_start__gte=filters.data_interval.start, data_interval_end__lte=filters.data_interval.end
        )
    if filters.statuses:
        runs = runs.filter(status__in=filters.statuses)
    return [
        to_run_detail(run)
        for run in select_page(runs, page, ordering_fields=contracts.BATCH_EXPORT_RUN_ORDERING_FIELDS)
    ]


def get_run(team_id: int, export_id: UUID, run_id: UUID) -> contracts.BatchExportRunDetail:
    return to_run_detail(_get_run(team_id, export_id, run_id))


def retry_run(team_id: int, export_id: UUID, run_id: UUID) -> str:
    """Backfill the data interval of a run, and return the backfill id."""
    run = _get_run(team_id, export_id, run_id)
    return backfill_export(
        sync_connect(),
        str(run.batch_export_id),
        team_id,
        run.data_interval_start,
        run.data_interval_end,
    )


def cancel_run(team_id: int, export_id: UUID, run_id: UUID) -> None:
    run = _get_run(team_id, export_id, run_id)
    if run.status not in _CANCELLABLE_STATUSES:
        raise contracts.InvalidBatchExportRunRequestError(f"Cannot cancel a run that is in '{run.status}' status")

    temporal = sync_connect()
    try:
        cancel_running_batch_export_run(temporal, run)
    except Exception as e:
        # It could be the case that the run is already cancelled but our database hasn't been updated yet. In
        # this case, we can just ignore the error but log it for visibility (in case there is an actual issue).
        LOGGER.warning("Error cancelling batch export run: %s", e)
