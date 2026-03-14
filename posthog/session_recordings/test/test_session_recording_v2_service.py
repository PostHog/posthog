from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import (
    FIVE_SECONDS,
    RecordingBlock,
    list_blocks,
    listing_cache_key,
)


@override_settings(RECORDING_API_URL="http://recording-api:6738", INTERNAL_API_SECRET="test-secret")
class TestSessionRecordingV2Service(TestCase):
    def setUp(self):
        self.team = Mock(id=1)
        self.recording = Mock(spec=SessionRecording)
        self.recording.session_id = "test_session"
        self.recording.team = self.team
        self.recording.team_id = self.team.id
        self.recording.start_time = None

        from django.core.cache import cache

        cache.clear()

    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_returns_blocks_from_recording_api(self, mock_fetch):
        mock_fetch.return_value = [
            RecordingBlock(
                key="bucket/key1",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="bucket/key2",
                start_byte=0,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]

        blocks = list_blocks(self.recording)

        assert blocks == [
            RecordingBlock(
                key="bucket/key1",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="bucket/key2",
                start_byte=0,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]
        mock_fetch.assert_called_once_with("test_session", 1)

    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_returns_empty_list_on_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("connection refused")

        blocks = list_blocks(self.recording)

        assert blocks == []

    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_returns_empty_list_when_no_blocks(self, mock_fetch):
        mock_fetch.return_value = []

        blocks = list_blocks(self.recording)

        assert blocks == []

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_caches_result(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.return_value = [
            RecordingBlock(
                key="bucket/key1",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]

        list_blocks(self.recording)

        expected_cache_key = listing_cache_key(self.recording)
        mock_cache.set.assert_called_once_with(
            expected_cache_key,
            [
                RecordingBlock(
                    key="bucket/key1",
                    start_byte=0,
                    end_byte=100,
                    start_timestamp="2024-01-01T00:00:00Z",
                    end_timestamp="2024-01-01T00:01:00Z",
                )
            ],
            timeout=FIVE_SECONDS,
        )

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_does_not_cache_empty_result(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.return_value = []

        list_blocks(self.recording)

        mock_cache.set.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_returns_cached_data_without_calling_api(self, mock_fetch, mock_cache):
        cached_blocks = [
            RecordingBlock(
                key="bucket/key1",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]
        mock_cache.get.return_value = cached_blocks

        blocks = list_blocks(self.recording)

        assert blocks == cached_blocks
        mock_fetch.assert_not_called()
        mock_cache.set.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api")
    def test_list_blocks_does_not_cache_on_error(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = Exception("timeout")

        list_blocks(self.recording)

        mock_cache.set.assert_not_called()
