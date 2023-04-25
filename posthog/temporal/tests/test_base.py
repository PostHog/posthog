import datetime as dt

import pytest
from asgiref.sync import sync_to_async

from posthog.models import ExportDestination, ExportRun, Organization, Team
from posthog.temporal.workflows.base import (
    CreateExportRunInputs,
    UpdateExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
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
    """Fixture providing an ExportDestination for testing."""
    dest = ExportDestination.objects.create(
        name="test-s3-dest",
        type="S3",
        team=team,
    )
    dest.save()

    yield dest

    dest.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_export_run(activity_environment, team, destination):
    """Test the create_export_run activity.

    We check if an ExportRun is created after the activity runs.
    """
    start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

    inputs = CreateExportRunInputs(
        team_id=team.id,
        destination_id=str(destination.id),
        schedule_id=None,
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id = await activity_environment.run(create_export_run, inputs)

    runs = ExportRun.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()

    run = await sync_to_async(runs.first)()
    assert run.data_interval_start == start
    assert run.data_interval_end == end


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_export_run_status(activity_environment, team, destination):
    """Test the export_run_status activity."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

    inputs = CreateExportRunInputs(
        team_id=team.id,
        destination_id=str(destination.id),
        schedule_id=None,
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id = await activity_environment.run(create_export_run, inputs)

    runs = ExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()
    assert run.status == "Starting"

    update_inputs = UpdateExportRunStatusInputs(
        run_id=str(run_id),
        status="Completed",
    )
    await activity_environment.run(update_export_run_status, update_inputs)

    runs = ExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()
    assert run.status == "Completed"
