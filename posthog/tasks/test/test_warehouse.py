from posthog.test.base import APIBaseTest
from unittest.mock import patch, MagicMock
from posthog.tasks.warehouse import check_synced_row_limits_of_team, capture_workspace_rows_synced_by_team
from posthog.warehouse.models import ExternalDataSource, ExternalDataJob
from freezegun import freeze_time
import datetime


class TestWarehouse(APIBaseTest):
    @patch("posthog.tasks.warehouse.MONTHLY_LIMIT", 100)
    @patch("posthog.tasks.warehouse.cancel_external_data_workflow")
    @patch("posthog.tasks.warehouse.pause_external_data_schedule")
    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_check_synced_row_limits_of_team(
        self,
        list_limited_team_attributes_mock: MagicMock,
        pause_schedule_mock: MagicMock,
        cancel_workflow_mock: MagicMock,
    ) -> None:
        list_limited_team_attributes_mock.return_value = [self.team.pk]

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

    @patch("posthog.tasks.warehouse.get_ph_client")
    @patch(
        "posthog.tasks.warehouse.DEFAULT_DATE_TIME",
        datetime.datetime(2023, 11, 7, 0, 0, 0, tzinfo=datetime.UTC),
    )
    @freeze_time("2023-11-07")
    def test_capture_workspace_rows_synced_by_team_month_cutoff(self, mock_get_ph_client: MagicMock) -> None:
        # external_data_workspace_last_synced_at unset

        mock_ph_client = MagicMock()
        mock_get_ph_client.return_value = mock_ph_client

        source = ExternalDataSource.objects.create(
            source_id="test_id",
            connection_id="fake connectino_id",
            destination_id="fake destination_id",
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

        with freeze_time("2023-11-07T16:50:49Z"):
            job = ExternalDataJob.objects.create(
                pipeline=source, workflow_id="fake_workflow_id", team=self.team, status="Running", rows_synced=100000
            )

        capture_workspace_rows_synced_by_team(self.team.pk)

        assert mock_ph_client.capture.call_count == 1
        mock_ph_client.capture.assert_called_with(
            self.team.pk,
            "$data_sync_job_completed",
            {
                "team_id": self.team.pk,
                "workspace_id": self.team.external_data_workspace_id,
                "count": job.rows_synced,
                "start_time": job.created_at,
                "job_id": str(job.pk),
            },
        )

        self.team.refresh_from_db()
        self.assertEqual(
            self.team.external_data_workspace_last_synced_at,
            datetime.datetime(2023, 11, 7, 16, 50, 49, tzinfo=datetime.UTC),
        )

    @patch("posthog.tasks.warehouse.get_ph_client")
    @patch(
        "posthog.tasks.warehouse.DEFAULT_DATE_TIME",
        datetime.datetime(2023, 11, 7, 0, 0, 0, tzinfo=datetime.UTC),
    )
    @freeze_time("2023-11-07")
    def test_capture_workspace_rows_synced_by_team_month_cutoff_field_set(self, mock_get_ph_client: MagicMock) -> None:
        mock_ph_client = MagicMock()
        mock_get_ph_client.return_value = mock_ph_client

        self.team.external_data_workspace_last_synced_at = datetime.datetime(
            2023, 10, 30, 19, 32, 41, tzinfo=datetime.UTC
        )
        self.team.save()

        source = ExternalDataSource.objects.create(
            source_id="test_id",
            connection_id="fake connectino_id",
            destination_id="fake destination_id",
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

        with freeze_time("2023-10-30T18:32:41Z"):
            ExternalDataJob.objects.create(
                pipeline=source, workflow_id="fake_workflow_id", team=self.team, status="Completed", rows_synced=97747
            )

        with freeze_time("2023-11-07T16:50:49Z"):
            job2 = ExternalDataJob.objects.create(
                pipeline=source, workflow_id="fake_workflow_id", team=self.team, status="Completed", rows_synced=93353
            )

        capture_workspace_rows_synced_by_team(self.team.pk)

        assert mock_ph_client.capture.call_count == 1
        mock_ph_client.capture.assert_called_with(
            self.team.pk,
            "$data_sync_job_completed",
            {
                "team_id": self.team.pk,
                "workspace_id": self.team.external_data_workspace_id,
                "count": job2.rows_synced,
                "start_time": job2.created_at,
                "job_id": str(job2.pk),
            },
        )

        self.team.refresh_from_db()
        self.assertEqual(
            self.team.external_data_workspace_last_synced_at,
            datetime.datetime(2023, 11, 7, 16, 50, 49, tzinfo=datetime.UTC),
        )
