"""
Test-support facade for batch_exports.

Test suites outside this product (core's email digest, the usage report, the integration
and team-deletion API tests, the activity-log helper, the HogQL system-table isolation
tests, the shared Temporal test utilities) plant batch exports and their runs. They get
them here instead of importing the models.

Ids go in and ids come out, so a caller never holds an ORM instance. Reads return the
same contracts ``facade/api.py`` returns.

``service.py`` and ``temporalio`` are imported at call time, for the reason
``facade/api.py`` documents: this module must stay off the ``django.setup()`` path.
"""

import datetime as dt
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from products.batch_exports.backend.models.batch_export import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportOnDemand,
    BatchExportRun,
)

from . import contracts
from .api import _to_backfill_summary, _to_detail, _to_run_summary

if TYPE_CHECKING:
    from temporalio.client import Client

    from products.batch_exports.backend.service import NoOpInputs


def create_batch_export(
    team_id: int,
    *,
    name: str,
    destination_type: str,
    destination_config: Mapping[str, object],
    interval: str = "hour",
    paused: bool = False,
    model: str | None = None,
    timezone: str | None = None,
    interval_offset: int | None = None,
    sync_schedule: bool = False,
) -> UUID:
    """Plant a scheduled batch export and return its id.

    ``sync_schedule`` also creates the Temporal schedule, which a test only needs when it
    exercises the schedule itself. It costs a Temporal connection, so it is off by default.
    """
    destination = BatchExportDestination(type=destination_type, config=dict(destination_config))
    batch_export = BatchExport(
        team_id=team_id,
        destination=destination,
        name=name,
        interval=interval,
        paused=paused,
        model=model if model is not None else BatchExport.Model.EVENTS,
        timezone=timezone or "UTC",
        interval_offset=interval_offset,
    )

    if sync_schedule:
        from products.batch_exports.backend.service import sync_batch_export

        sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()

    return batch_export.id


def create_batch_export_on_demand(
    team_id: int,
    *,
    destination_type: str,
    destination_config: Mapping[str, object],
    model: str | None = None,
) -> UUID:
    """Plant an on-demand batch export and return its id."""
    destination = BatchExportDestination.objects.create(type=destination_type, config=dict(destination_config))
    return (
        BatchExportOnDemand.objects.for_team(team_id)
        .create(
            team_id=team_id,
            destination=destination,
            model=model if model is not None else BatchExportOnDemand.Model.EVENTS,
        )
        .id
    )


def create_batch_export_run(
    *,
    status: str,
    data_interval_end: dt.datetime,
    data_interval_start: dt.datetime | None = None,
    batch_export_id: UUID | None = None,
    on_demand_id: UUID | None = None,
    records_completed: int | None = None,
    finished_at: dt.datetime | None = None,
) -> UUID:
    """Plant a run of a scheduled or an on-demand export, and return its id.

    A run belongs to exactly one of the two, which a check constraint enforces.
    """
    if (batch_export_id is None) == (on_demand_id is None):
        raise ValueError("Pass exactly one of batch_export_id or on_demand_id")

    return BatchExportRun.objects.create(
        batch_export_id=batch_export_id,
        batch_export_on_demand_id=on_demand_id,
        status=status,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        records_completed=records_completed,
        finished_at=finished_at,
    ).id


def create_backfill(
    batch_export_id: UUID,
    *,
    team_id: int,
    status: str,
    start_at: dt.datetime | None = None,
    end_at: dt.datetime | None = None,
) -> UUID:
    """Plant a backfill of a scheduled export and return its id."""
    return BatchExportBackfill.objects.create(
        batch_export_id=batch_export_id,
        team_id=team_id,
        status=status,
        start_at=start_at,
        end_at=end_at,
    ).id


def update_batch_export(batch_export_id: UUID, **fields: Any) -> contracts.BatchExportDetail:
    """Set fields on a batch export and return what it looks like afterwards."""
    batch_export = BatchExport.objects.select_related("destination").get(id=batch_export_id)
    for name, value in fields.items():
        setattr(batch_export, name, value)
    batch_export.save()
    return _to_detail(batch_export)


def delete_batch_export(batch_export_id: UUID, temporal_client: "Client | None" = None) -> None:
    """Remove a batch export row outright, and its Temporal schedule when a client is given.

    This is the teardown counterpart of ``create_batch_export``, not the product's delete
    capability: it drops the row rather than marking it deleted. A schedule that is already
    gone is not an error here.
    """
    if temporal_client is not None:
        import temporalio.service
        from asgiref.sync import async_to_sync

        handle = temporal_client.get_schedule_handle(str(batch_export_id))
        try:
            async_to_sync(handle.delete)()
        except temporalio.service.RPCError as e:
            # Anything else - an auth failure, an unreachable server - must still surface,
            # or a broken Temporal connection reads as a clean teardown.
            if e.status != temporalio.service.RPCStatusCode.NOT_FOUND:
                raise

    BatchExport.objects.filter(id=batch_export_id).delete()


def list_runs(batch_export_id: UUID, limit: int = 100) -> list[contracts.BatchExportRunSummary]:
    """Return an export's runs, most recently created first."""
    runs = BatchExportRun.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit]
    return [_to_run_summary(run) for run in runs]


def list_backfills(batch_export_id: UUID, limit: int = 100) -> list[contracts.BatchExportBackfillSummary]:
    """Return an export's backfills, most recently created first."""
    backfills = BatchExportBackfill.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit]
    return [_to_backfill_summary(backfill) for backfill in backfills]


def noop_inputs(*, arg: str, team_id: int, batch_export_id: str) -> "NoOpInputs":
    """Build the inputs of the no-op workflow, which core uses to exercise the payload codec.

    A builder rather than a re-export of the class: ``NoOpInputs`` lives in ``service.py``,
    which is not a wiring location, so handing the class out would be a facade leak.
    """
    from products.batch_exports.backend.service import NoOpInputs

    return NoOpInputs(arg=arg, team_id=team_id, batch_export_id=batch_export_id)
