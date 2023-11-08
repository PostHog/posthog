from posthog.test.base import APIBaseTest
import datetime
from unittest.mock import patch, MagicMock
from posthog.tasks.warehouse import _traverse_jobs_by_field, calculate_workspace_rows_synced_by_team
from freezegun import freeze_time


class TestWarehouse(APIBaseTest):
    @patch("posthog.tasks.warehouse.send_request")
    @freeze_time("2023-11-07")
    def test_traverse_jobs_by_field(self, send_request_mock):
        send_request_mock.return_value = {
            "data": [
                {
                    "jobId": 5827835,
                    "status": "succeeded",
                    "jobType": "sync",
                    "startTime": "2023-11-07T16:50:49Z",
                    "connectionId": "fake",
                    "lastUpdatedAt": "2023-11-07T16:52:54Z",
                    "duration": "PT2M5S",
                    "rowsSynced": 93353,
                },
                {
                    "jobId": 5783573,
                    "status": "succeeded",
                    "jobType": "sync",
                    "startTime": "2023-11-05T18:32:41Z",
                    "connectionId": "fake-2",
                    "lastUpdatedAt": "2023-11-05T18:35:11Z",
                    "duration": "PT2M30S",
                    "rowsSynced": 97747,
                },
            ]
        }
        mock_capture = MagicMock()
        response = _traverse_jobs_by_field(mock_capture, self.team, "fake-url", "rowsSynced")

        self.assertEqual(
            response,
            [
                {"count": 93353, "startTime": "2023-11-07T16:50:49Z"},
                {"count": 97747, "startTime": "2023-11-05T18:32:41Z"},
            ],
        )

        self.assertEqual(mock_capture.capture.call_count, 2)
        mock_capture.capture.assert_called_with(
            self.team.pk,
            "external data sync job",
            {
                "count": 97747,
                "workspace_id": self.team.external_data_workspace_id,
                "team_id": self.team.pk,
                "team_uuid": self.team.uuid,
                "startTime": "2023-11-05T18:32:41Z",
                "job_id": "5783573",
            },
        )

    @patch("posthog.tasks.warehouse._traverse_jobs_by_field")
    @patch("posthog.tasks.warehouse.get_ph_client")
    @freeze_time("2023-11-07")
    def test_calculate_workspace_rows_synced_by_team(self, mock_capture, traverse_jobs_mock):
        traverse_jobs_mock.return_value = [
            {"count": 97747, "startTime": "2023-11-05T18:32:41Z"},
            {"count": 93353, "startTime": "2023-11-07T16:50:49Z"},
        ]

        calculate_workspace_rows_synced_by_team(self.team.pk)

        self.team.refresh_from_db()
        self.assertEqual(self.team.external_data_workspace_rows_synced_in_month, 191100)
        self.assertEqual(
            self.team.external_data_workspace_last_synced,
            datetime.datetime(2023, 11, 7, 16, 50, 49, tzinfo=datetime.timezone.utc),
        )

    @patch("posthog.tasks.warehouse._traverse_jobs_by_field")
    @patch("posthog.tasks.warehouse.get_ph_client")
    @freeze_time("2023-11-07")
    def test_calculate_workspace_rows_synced_by_team_month_cutoff(self, mock_capture, traverse_jobs_mock):
        # external_data_workspace_last_synced unset
        traverse_jobs_mock.return_value = [
            {"count": 97747, "startTime": "2023-10-30T18:32:41Z"},
            {"count": 93353, "startTime": "2023-11-07T16:50:49Z"},
        ]

        calculate_workspace_rows_synced_by_team(self.team.pk)

        self.team.refresh_from_db()
        self.assertEqual(self.team.external_data_workspace_rows_synced_in_month, 93353)
        self.assertEqual(
            self.team.external_data_workspace_last_synced,
            datetime.datetime(2023, 11, 7, 16, 50, 49, tzinfo=datetime.timezone.utc),
        )

    @patch("posthog.tasks.warehouse._traverse_jobs_by_field")
    @patch("posthog.tasks.warehouse.get_ph_client")
    @freeze_time("2023-11-07")
    def test_calculate_workspace_rows_synced_by_team_month_cutoff_field_set(self, mock_capture, traverse_jobs_mock):
        self.team.external_data_workspace_last_synced = datetime.datetime(
            2023, 10, 29, 18, 32, 41, tzinfo=datetime.timezone.utc
        )
        traverse_jobs_mock.return_value = [
            {"count": 97747, "startTime": "2023-10-30T18:32:41Z"},
            {"count": 93353, "startTime": "2023-11-07T16:50:49Z"},
        ]

        calculate_workspace_rows_synced_by_team(self.team.pk)

        self.team.refresh_from_db()
        self.assertEqual(self.team.external_data_workspace_rows_synced_in_month, 93353)
        self.assertEqual(
            self.team.external_data_workspace_last_synced,
            datetime.datetime(2023, 11, 7, 16, 50, 49, tzinfo=datetime.timezone.utc),
        )
