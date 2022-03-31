import unittest
from unittest.mock import patch

from posthog.settings import CONSTANCE_CONFIG
from posthog.tasks.delete_session_recordings import delete_session_recording_files_order_than_ttl


class TestDeleteSessionRecordingsTask(unittest.TestCase):
    def test_logs_on_error(self):
        with self.assertLogs(level="ERROR") as log:
            CONSTANCE_CONFIG["RECORDINGS_TTL_WEEKS"] = ("a", "description")
            delete_session_recording_files_order_than_ttl()

        logged_warning = log.records[0].__dict__
        self.assertEqual(logged_warning["levelname"], "ERROR")
        self.assertEqual(logged_warning["msg"]["event"], "session_recordings_file_deletion_failed")
        self.assertEqual(logged_warning["msg"]["ttl_weeks"], "a")
        self.assertEqual(logged_warning["msg"]["file_deletion_time_delta"], "None")
        self.assertIsInstance(logged_warning["msg"]["exception"], ValueError)

    @patch("posthog.tasks.delete_session_recordings.object_storage")
    def test_calls_to_delete_files(self, mock_storage):
        delete_session_recording_files_order_than_ttl()
        mock_storage.delete_older_than.assert_called_once()

    @patch("posthog.tasks.delete_session_recordings.gauge")
    @patch("posthog.tasks.delete_session_recordings.object_storage")
    def test_sets_gauge_on_delete(self, mock_storage, mock_gauge):
        mock_storage.delete_older_than.return_value = 4
        delete_session_recording_files_order_than_ttl()
        mock_gauge.assert_called_once_with("posthog_celery_session_recordings_deletion", 4)
