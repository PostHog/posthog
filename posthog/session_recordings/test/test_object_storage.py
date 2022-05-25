import json
from unittest.mock import patch

from posthog.session_recordings.object_storage import read_snapshot_data
from posthog.test.base import APIBaseTest


class TestObjectStorage(APIBaseTest):
    def test_if_object_storage_is_disabled_returns_data(self) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            snapshot_data = {"data": "tomato", "object_storage_path": "session_id/id/index"}
            actual = read_snapshot_data(json.dumps(snapshot_data), 1)

            self.assertEqual(actual, snapshot_data)

    @patch("posthog.session_recordings.object_storage.object_storage")
    @patch("statshog.defaults.django.statsd.incr")
    def test_if_object_storage_is_enabled_loads_from_object_storage(self, statsd_incr, object_storage) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            object_storage.read.return_value = "something from disk"
            snapshot_data = {"data": "tomato", "object_storage_path": "session_id/id/index"}
            actual = read_snapshot_data(json.dumps(snapshot_data), 1)

            self.assertEqual(actual, {"data": "something from disk", "object_storage_path": "session_id/id/index"})
            statsd_incr_first_call = statsd_incr.call_args_list[0]
            self.assertEqual(statsd_incr_first_call.args[0], "session_recording.object_storage.read.success")
            self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"team_id": 1}})

    @patch("posthog.session_recordings.object_storage.object_storage")
    @patch("statshog.defaults.django.statsd.incr")
    def test_if_object_storage_fails_returns_data(self, statsd_incr, object_storage) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            object_storage.read.side_effect = Exception("a very bad error")
            snapshot_data = {"data": "tomato", "object_storage_path": "session_id/id/index"}
            actual = read_snapshot_data(json.dumps(snapshot_data), 1)

            self.assertEqual(actual, {"data": "tomato", "object_storage_path": "session_id/id/index"})
            statsd_incr_first_call = statsd_incr.call_args_list[0]
            self.assertEqual(statsd_incr_first_call.args[0], "session_recording.object_storage.read.error")
            self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"team_id": 1}})
