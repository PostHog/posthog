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
from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)
from posthog.test.base import TransactionTestCase


class RunUpdatesTest(TransactionTestCase):
    available_apps = ["posthog"]

    @pytest.fixture(autouse=True)
    def activity_environment_fixture(self, activity_environment):
        """Fixture providing an Organization for testing."""
        self.activity_environment = activity_environment

    @pytest.fixture(autouse=True)
    def organization(self):
        """Fixture providing an Organization for testing."""
        self.org = Organization.objects.create(name="test-org")
        self.org.save()

        yield

        self.org.delete()

    @pytest.fixture(autouse=True)
    def team_fixture(self, organization):
        """Fixture providing a Team for testing."""
        self.team = Team.objects.create(organization=self.org)
        self.team.save()

        yield

        self.team.delete()

    @pytest.fixture(autouse=True)
    def destination(self, team_fixture):
        """Fixture providing an BatchExportDestination for testing."""
        self.dest = BatchExportDestination.objects.create(
            type="S3",
            config={
                "bucket_name": "bucket",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "batch_window_size": 3600,
                "aws_access_key_id": "key_id",
                "aws_secret_access_key": "secret",
            },
        )
        self.dest.save()

        yield

        self.dest.delete()

    @pytest.fixture(autouse=True)
    def batch_export(self, team_fixture, destination):
        """A test BatchExport."""
        self.batch_export = BatchExport.objects.create(
            name="test export", team=self.team, destination=self.dest, interval="hour"
        )
        self.batch_export.save()

        yield

        self.batch_export.delete()

    @pytest.mark.asyncio
    async def test_create_export_run(self):
        """Test the create_export_run activity.

        We check if an BatchExportRun is created after the activity runs.
        """
        start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
        end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

        inputs = CreateBatchExportRunInputs(
            team_id=self.team.id,
            batch_export_id=str(self.batch_export.id),
            data_interval_start=start.isoformat(),
            data_interval_end=end.isoformat(),
        )

        run_id = await self.activity_environment.run(create_export_run, inputs)

        runs = BatchExportRun.objects.filter(id=run_id)
        assert await sync_to_async(runs.exists)()  # type:ignore

        run = await sync_to_async(runs.first)()  # type:ignore
        assert run.data_interval_start == start
        assert run.data_interval_end == end

    @pytest.mark.asyncio
    async def test_update_export_run_status(self):
        """Test the export_run_status activity."""
        start = dt.datetime(2023, 4, 24, tzinfo=dt.timezone.utc)
        end = dt.datetime(2023, 4, 25, tzinfo=dt.timezone.utc)

        inputs = CreateBatchExportRunInputs(
            team_id=self.team.id,
            batch_export_id=str(self.batch_export.id),
            data_interval_start=start.isoformat(),
            data_interval_end=end.isoformat(),
        )

        run_id = await self.activity_environment.run(create_export_run, inputs)

        runs = BatchExportRun.objects.filter(id=run_id)
        run = await sync_to_async(runs.first)()  # type:ignore
        assert run.status == "Starting"

        update_inputs = UpdateBatchExportRunStatusInputs(
            id=str(run_id),
            status="Completed",
        )
        await self.activity_environment.run(update_export_run_status, update_inputs)

        runs = BatchExportRun.objects.filter(id=run_id)
        run = await sync_to_async(runs.first)()  # type:ignore
        assert run.status == "Completed"
