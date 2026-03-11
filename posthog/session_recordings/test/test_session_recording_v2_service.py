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

    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_returns_blocks_from_recording_api(self, mock_fetch):
        mock_fetch.return_value = [
            RecordingBlock(key="bucket/key1", start=0, end=100),
            RecordingBlock(key="bucket/key2", start=0, end=200),
        ]

        blocks = list_blocks(self.recording)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].key, "bucket/key1")
        self.assertEqual(blocks[0].start, 0)
        self.assertEqual(blocks[0].end, 100)
        self.assertEqual(blocks[1].key, "bucket/key2")
        mock_fetch.assert_called_once_with("test_session", 1)

    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_returns_empty_list_on_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("connection refused")

        blocks = list_blocks(self.recording)

        self.assertEqual(blocks, [])

    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_returns_empty_list_when_no_blocks(self, mock_fetch):
        mock_fetch.return_value = []

        blocks = list_blocks(self.recording)

        self.assertEqual(blocks, [])

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_caches_result(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.return_value = [RecordingBlock(key="bucket/key1", start=0, end=100)]

        list_blocks(self.recording)

        expected_cache_key = listing_cache_key(self.recording)
        mock_cache.set.assert_called_once_with(
            expected_cache_key,
            [RecordingBlock(key="bucket/key1", start=0, end=100)],
            timeout=FIVE_SECONDS,
        )

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_does_not_cache_empty_result(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.return_value = []

        list_blocks(self.recording)

        mock_cache.set.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_returns_cached_data_without_calling_api(self, mock_fetch, mock_cache):
        cached_blocks = [RecordingBlock(key="bucket/key1", start=0, end=100)]
        mock_cache.get.return_value = cached_blocks

        blocks = list_blocks(self.recording)

        self.assertEqual(blocks, cached_blocks)
        mock_fetch.assert_not_called()
        mock_cache.set.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service._fetch_blocks_from_recording_api")
    def test_list_blocks_does_not_cache_on_error(self, mock_fetch, mock_cache):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = Exception("timeout")

        list_blocks(self.recording)

        mock_cache.set.assert_not_called()
