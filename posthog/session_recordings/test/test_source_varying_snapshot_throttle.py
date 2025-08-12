from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.http import HttpResponse
from django.utils.timezone import now
from parameterized import parameterized
from rest_framework import status
from django.core.cache import cache

from posthog.models import PersonalAPIKey, SessionRecording
from posthog.models.instance_setting import set_instance_setting
from posthog.models.personal_api_key import hash_key_value
from posthog.test.base import APIBaseTest


class TestSourceVaryingSnapshotThrottle(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()  # Clear rate limit cache between tests

        self.recording_id = "test_recording_123"

        personal_api_key = PersonalAPIKey.objects.create(
            label="Test API Key",
            user=self.user,
            secure_value=hash_key_value("test_api_key"),
        )
        self.personal_api_key = personal_api_key

        self.base_headers = {
            "Authorization": f"Bearer test_api_key",
        }

        set_instance_setting("RATE_LIMIT_ENABLED", True)

    @parameterized.expand(
        [
            ("realtime", 1),
            ("blob", 30),
            ("blob_v2", 120),
        ]
    )
    @patch(
        "posthog.session_recordings.session_recording_api.SessionRecordingViewSet._stream_blob_to_client",
        return_value=HttpResponse(),
    )
    @patch(
        "posthog.session_recordings.session_recording_api.SessionRecordingViewSet._gather_session_recording_sources",
        return_value=[],
    )
    @patch("posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists", return_value=True)
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.client")
    @patch(
        "posthog.session_recordings.session_recording_api.object_storage.list_objects", return_value=["test-blob.jsonl"]
    )
    @patch(
        "posthog.session_recordings.realtime_snapshots.get_realtime_snapshots", return_value=["snapshot1", "snapshot2"]
    )
    def test_different_sources_get_different_rate_limits(
        self,
        source: str,
        expected_allowed_requests: int,
        _mock_get_realtime_snapshots,
        _mock_list_objects,
        mock_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
        _mock_gather_sources,
        _mock_stream_blob_to_client,
    ):
        mock_get_session_recording.return_value = SessionRecording(
            session_id=self.recording_id, team=self.team, deleted=False
        )

        mock_blocks = [MagicMock(url="http://test.com/block0")]
        mock_list_blocks.return_value = mock_blocks

        mock_client_instance = MagicMock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.fetch_block.return_value = '{"timestamp": 1000, "type": "snapshot"}'

        url = f"/api/projects/{self.team.id}/session_recordings/{self.recording_id}/snapshots?source={source}"
        if source == "blob_v2":
            url += "&blob_key=0"

        allowed_count = 0

        self.client.logout()
        for _ in range(150):
            with self.settings(API_V1_DEPRECATION_DATE=(now() + timedelta(days=365)).isoformat()):
                response = self.client.get(url, headers=self.base_headers)
            if response.status_code == status.HTTP_200_OK:
                allowed_count += 1
            elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break
            else:
                # If we get other errors, fail the test
                self.fail(f"Unexpected status code {response.status_code}: {response.content}")

        tolerance = 2 if expected_allowed_requests > 5 else 1
        assert (
            abs(allowed_count - expected_allowed_requests) <= tolerance
        ), f"Source '{source}' should allow ~{expected_allowed_requests} requests but allowed {allowed_count}"
