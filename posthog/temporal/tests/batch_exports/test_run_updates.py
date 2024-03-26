import datetime as dt

import pytest
from asgiref.sync import sync_to_async

from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    Organization,
    Team,
)
from posthog.temporal.batch_exports.batch_exports import (
    FinishBatchExportRunInputs,
    StartBatchExportRunInputs,
    finish_batch_export_run,
    start_batch_export_run,
)


@pytest.fixture
def organization():
    """Fixture providing an Organization for testing."""
    org = Organization.objects.create(name="test-org")
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """Fixture providing a Team for testing."""
    team = Team.objects.create(organization=organization)
    team.save()

    yield team

    team.delete()


@pytest.fixture
def destination(team):
    """Fixture providing an BatchExportDestination for testing."""
    dest = BatchExportDestination.objects.create(
        type="S3",
        config={
            "bucket_name": "bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "key_id",
            "aws_secret_access_key": "secret",
        },
    )
    dest.save()

    yield dest

    dest.delete()


@pytest.fixture
def batch_export(destination, team):
    """A test BatchExport."""
    batch_export = BatchExport.objects.create(name="test export", team=team, destination=destination, interval="hour")

    batch_export.save()

    yield batch_export

    batch_export.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_batch_export_run(activity_environment, team, batch_export):
    """Test the 'start_batch_export_run' activity.

    We check if a 'BatchExportRun' is created after the activity runs.
    """
    start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id, records_total_count = await activity_environment.run(start_batch_export_run, inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()  # type:ignore

    run = await sync_to_async(runs.first)()  # type:ignore
    assert run is not None
    assert run.data_interval_start == start
    assert run.data_interval_end == end
    assert run.records_total_count == records_total_count


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finish_batch_export_run(activity_environment, team, batch_export):
    """Test the export_run_status activity."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id, records_total_count = await activity_environment.run(start_batch_export_run, inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()  # type:ignore
    assert run is not None
    assert run.status == "Starting"
    assert run.records_total_count == records_total_count

    finish_inputs = FinishBatchExportRunInputs(
        id=str(run_id),
        status="Completed",
        team_id=inputs.team_id,
    )
    await activity_environment.run(finish_batch_export_run, finish_inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()  # type:ignore
    assert run is not None
    assert run.status == "Completed"
    assert run.records_total_count == records_total_count
