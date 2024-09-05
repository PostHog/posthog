from posthog.test.base import APIBaseTest
from unittest.mock import patch, MagicMock
from posthog.tasks.warehouse import (
    capture_workspace_rows_synced_by_team,
    validate_data_warehouse_table_columns,
    capture_external_data_rows_synced,
)
from posthog.warehouse.models import ExternalDataSource, ExternalDataJob
from freezegun import freeze_time
import datetime

from posthog.warehouse.models.table import DataWarehouseTable


class TestWarehouse(APIBaseTest):
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

    @patch("posthog.tasks.warehouse.get_ph_client")
    def test_validate_data_warehouse_table_columns(self, mock_get_ph_client: MagicMock) -> None:
        mock_ph_client = MagicMock()
        mock_get_ph_client.return_value = mock_ph_client

        table = DataWarehouseTable.objects.create(
            name="table_name",
            format="Parquet",
            team=self.team,
            columns={"some_columns": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"}},
        )

        with patch.object(DataWarehouseTable, "validate_column_type", return_value=True):
            validate_data_warehouse_table_columns(self.team.pk, str(table.id))

        table.refresh_from_db()

        assert table.columns.get("some_columns").get("valid") is True
        mock_ph_client.capture.assert_called_once()
        mock_ph_client.shutdown.assert_called_once()

    @patch("posthog.tasks.warehouse.capture_workspace_rows_synced_by_team.delay")
    def test_capture_external_data_rows_synced(self, mock_capture_workspace_rows_synced_by_team: MagicMock) -> None:
        ExternalDataSource.objects.create(
            source_id="test_id",
            connection_id="fake connectino_id",
            destination_id="fake destination_id",
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

        ExternalDataSource.objects.create(
            source_id="another_id",
            connection_id="fake connectino_id",
            destination_id="fake destination_id",
            team=self.team,
            status="Running",
            source_type="Stripe",
        )

        capture_external_data_rows_synced()

        assert mock_capture_workspace_rows_synced_by_team.call_count == 1
