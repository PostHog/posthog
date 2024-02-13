from posthog.test.base import APIBaseTest
from unittest.mock import patch, MagicMock
from posthog.tasks.warehouse import (
    check_synced_row_limits_of_team,
)
from posthog.warehouse.models import ExternalDataSource, ExternalDataJob


class TestWarehouse(APIBaseTest):
    @patch("posthog.tasks.warehouse.MONTHLY_LIMIT", 100)
    @patch("posthog.tasks.warehouse.cancel_external_data_workflow")
    @patch("posthog.tasks.warehouse.pause_external_data_schedule")
    def test_check_synced_row_limits_of_team(
        self, pause_schedule_mock: MagicMock, cancel_workflow_mock: MagicMock
    ) -> None:
        source = ExternalDataSource.objects.create(
            source_id="test_id",
            connection_id="fake connectino_id",
            destination_id="fake destination_id",
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

        job = ExternalDataJob.objects.create(
            pipeline=source, workflow_id="fake_workflow_id", team=self.team, status="Running", rows_synced=100000
        )

        check_synced_row_limits_of_team(self.team.pk)

        source.refresh_from_db()
        self.assertEqual(source.status, ExternalDataSource.Status.PAUSED)

        job.refresh_from_db()
        self.assertEqual(job.status, ExternalDataJob.Status.CANCELLED)

        self.assertEqual(pause_schedule_mock.call_count, 1)
        self.assertEqual(cancel_workflow_mock.call_count, 1)
