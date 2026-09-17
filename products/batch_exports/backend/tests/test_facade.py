import datetime as dt

import pytest
from unittest import mock

import temporalio.service
from asgiref.sync import async_to_sync
from temporalio.client import Client

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.facade import api, contracts, testing
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportRun
from products.batch_exports.backend.service import BatchExportServiceScheduleNotFound

pytestmark = [pytest.mark.django_db]

# The billing window the aggregate tests query. Nothing under test reads the wall clock, so
# fixed instants stay meaningful however long this test lives.
WINDOW_BEGIN = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
WINDOW_END = WINDOW_BEGIN + dt.timedelta(days=1)
IN_WINDOW = WINDOW_BEGIN + dt.timedelta(hours=1)

S3 = BatchExportDestination.Destination.S3
HTTP = BatchExportDestination.Destination.HTTP
NOOP = BatchExportDestination.Destination.NOOP
WORKFLOWS = BatchExportDestination.Destination.WORKFLOWS
FILE_DOWNLOAD = BatchExportDestination.Destination.FILE_DOWNLOAD


@pytest.fixture
def organization():
    return create_organization("BatchExportsFacadeTestOrg")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


def _export(team, *, name="export", destination_type=S3, config=None, **fields):
    return testing.create_batch_export(
        team.pk,
        name=name,
        destination_type=destination_type,
        destination_config=config or {},
        **fields,
    )


def _run(*, finished_at, records=0, status=BatchExportRun.Status.COMPLETED, created_at=None, **parent):
    run_id = testing.create_batch_export_run(
        status=status,
        data_interval_start=finished_at - dt.timedelta(hours=1),
        data_interval_end=finished_at,
        records_completed=records,
        finished_at=finished_at,
        **parent,
    )
    if created_at is not None:
        # created_at is auto_now_add, so the ordering a test needs can only be set afterwards.
        BatchExportRun.objects.filter(id=run_id).update(created_at=created_at)
    return run_id


def test_billable_rows_exported_sums_scheduled_and_on_demand_runs_per_team(team):
    scheduled = _export(team, name="scheduled")
    on_demand = testing.create_batch_export_on_demand(team.pk, destination_type=FILE_DOWNLOAD, destination_config={})

    _run(batch_export_id=scheduled, finished_at=IN_WINDOW, records=10)
    _run(batch_export_id=scheduled, finished_at=IN_WINDOW, records=5)
    _run(on_demand_id=on_demand, finished_at=IN_WINDOW, records=7)
    _run(batch_export_id=scheduled, finished_at=WINDOW_END + dt.timedelta(hours=1), records=100)
    _run(batch_export_id=scheduled, finished_at=IN_WINDOW, records=100, status=BatchExportRun.Status.FAILED)

    assert api.get_teams_with_billable_rows_exported(WINDOW_BEGIN, WINDOW_END) == [
        contracts.TeamTotal(team_id=team.pk, total=22)
    ]


@pytest.mark.parametrize(
    "destination_type,export_fields,deleted",
    [
        (HTTP, {}, False),
        (WORKFLOWS, {}, False),
        (S3, {"model": BatchExport.Model.HOGQL}, False),
        (S3, {}, True),
    ],
    ids=["http destination", "workflows destination", "hogql model", "deleted export"],
)
def test_billable_rows_exported_drops_non_billable_runs(team, destination_type, export_fields, deleted):
    export_id = _export(team, destination_type=destination_type, **export_fields)
    _run(batch_export_id=export_id, finished_at=IN_WINDOW, records=10)
    if deleted:
        testing.update_batch_export(export_id, deleted=True)

    assert api.get_teams_with_billable_rows_exported(WINDOW_BEGIN, WINDOW_END) == []


def test_latest_failed_runs_reports_only_exports_whose_most_recent_run_failed(team):
    recovered = _export(team, name="recovered")
    _run(
        batch_export_id=recovered,
        finished_at=IN_WINDOW,
        status=BatchExportRun.Status.FAILED,
        created_at=IN_WINDOW,
    )
    _run(batch_export_id=recovered, finished_at=IN_WINDOW, created_at=IN_WINDOW + dt.timedelta(hours=1))

    failing = _export(team, name="failing")
    _run(batch_export_id=failing, finished_at=IN_WINDOW, created_at=IN_WINDOW)
    _run(
        batch_export_id=failing,
        finished_at=IN_WINDOW + dt.timedelta(hours=1),
        status=BatchExportRun.Status.TIMEDOUT,
        created_at=IN_WINDOW + dt.timedelta(hours=1),
    )

    assert api.list_latest_failed_runs(team.pk) == [
        contracts.FailedBatchExportRun(
            export_id=failing,
            export_name="failing",
            error=None,
            failed_at=IN_WINDOW + dt.timedelta(hours=1),
        )
    ]


@pytest.mark.parametrize("field", ["paused", "deleted"])
def test_latest_failed_runs_ignores_paused_and_deleted_exports(team, field):
    export_id = _export(team)
    _run(batch_export_id=export_id, finished_at=IN_WINDOW, status=BatchExportRun.Status.FAILED)
    testing.update_batch_export(export_id, **{field: True})

    assert api.list_latest_failed_runs(team.pk) == []


def test_run_failure_describes_a_scheduled_export(team):
    export_id = _export(team, name="nightly")
    run_id = _run(batch_export_id=export_id, finished_at=IN_WINDOW, status=BatchExportRun.Status.FAILED)

    failure = api.get_run_failure(run_id)

    assert failure is not None
    assert (failure.run_id, failure.team_id, failure.export_id, failure.export_name) == (
        run_id,
        team.pk,
        export_id,
        "nightly",
    )


def test_run_failure_is_none_for_an_on_demand_export(team):
    on_demand = testing.create_batch_export_on_demand(team.pk, destination_type=FILE_DOWNLOAD, destination_config={})
    run_id = _run(on_demand_id=on_demand, finished_at=IN_WINDOW, status=BatchExportRun.Status.FAILED)

    assert api.get_run_failure(run_id) is None


def test_batch_export_by_name_returns_the_stored_destination(team):
    export_id = _export(team, name="migration", destination_type=HTTP, config={"url": "https://example.com/batch"})

    detail = api.get_batch_export_by_name(team.pk, "migration", HTTP)

    assert detail is not None
    assert detail.id == export_id
    assert detail.team_id == team.pk
    assert detail.interval == "hour"
    assert detail.destination_type == HTTP
    assert detail.destination_config == {"url": "https://example.com/batch"}


def test_batch_export_by_name_is_none_when_nothing_matches(team):
    _export(team, name="migration", destination_type=HTTP)

    assert api.get_batch_export_by_name(team.pk, "migration", S3) is None


def test_batch_export_by_name_rejects_an_ambiguous_match(team):
    _export(team, name="migration", destination_type=HTTP)
    _export(team, name="migration", destination_type=HTTP)

    with pytest.raises(api.MultipleBatchExportsError):
        api.get_batch_export_by_name(team.pk, "migration", HTTP)


def test_latest_run_is_by_creation_and_latest_completed_run_is_by_finish(team):
    export_id = _export(team)
    finished_last = _run(
        batch_export_id=export_id,
        finished_at=IN_WINDOW + dt.timedelta(hours=2),
        created_at=IN_WINDOW,
    )
    _run(
        batch_export_id=export_id,
        finished_at=IN_WINDOW + dt.timedelta(hours=1),
        created_at=IN_WINDOW + dt.timedelta(hours=1),
    )
    created_last = _run(
        batch_export_id=export_id,
        finished_at=IN_WINDOW + dt.timedelta(hours=3),
        status=BatchExportRun.Status.FAILED,
        created_at=IN_WINDOW + dt.timedelta(hours=2),
    )

    latest = api.get_latest_run(export_id, team.pk)
    latest_completed = api.get_latest_completed_run(export_id, team.pk)

    assert latest is not None and latest.id == created_last
    assert latest_completed is not None and latest_completed.id == finished_last


def test_deleting_team_batch_exports_continues_past_a_missing_schedule(team):
    first = _export(team, name="first")
    second = _export(team, name="second")
    destination_ids = list(BatchExport.objects.filter(id__in=[first, second]).values_list("destination_id", flat=True))

    def delete_schedule(_temporal, schedule_id):
        if schedule_id == str(first):
            raise BatchExportServiceScheduleNotFound(schedule_id)

    with (
        mock.patch("products.batch_exports.backend.facade.api._temporal_client"),
        mock.patch("products.batch_exports.backend.service.batch_export_delete_schedule", side_effect=delete_schedule),
    ):
        api.delete_batch_exports_for_teams([team.pk])

    assert not BatchExport.objects.filter(id__in=[first, second]).exists()
    assert not BatchExportDestination.objects.filter(id__in=destination_ids).exists()


@pytest.fixture
def temporal():
    return sync_connect()


def _describe_schedule(temporal: Client, schedule_id: str):
    return async_to_sync(temporal.get_schedule_handle(schedule_id).describe)()


def test_creating_and_deleting_a_batch_export_manages_its_temporal_schedule(team, temporal):
    detail = api.create_batch_export(
        team.pk,
        name="facade export",
        destination_type=NOOP,
        destination_config={},
        interval="hour",
    )

    try:
        assert _describe_schedule(temporal, str(detail.id)).id == str(detail.id)
    finally:
        api.delete_batch_export(detail.id, team.pk)

    assert BatchExport.objects.get(id=detail.id).deleted is True
    with pytest.raises(temporalio.service.RPCError):
        _describe_schedule(temporal, str(detail.id))
