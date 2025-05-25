from datetime import datetime
from unittest.mock import Mock, patch

from django.test import TestCase
from freezegun import freeze_time

from posthog.session_recordings.models.metadata import RecordingBlockListing
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import (
    list_blocks,
    load_blocks,
    FIVE_SECONDS,
    ONE_DAY_IN_SECONDS,
)


class TestSessionRecordingV2Service(TestCase):
    def setUp(self):
        self.team = Mock(id=1)
        self.recording = Mock(spec=SessionRecording)
        self.recording.session_id = "test_id"
        self.recording.team = self.team
        self.recording.team.id = self.team.id
        self.recording.start_time = datetime(2024, 1, 1, 12, 20)

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_list_blocks_returns_empty_list_when_no_metadata(self, mock_replay_events):
        mock_replay_events.return_value.list_blocks.return_value = None
        blocks = list_blocks(self.recording)
        self.assertEqual(blocks, [])

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_list_blocks_returns_empty_list_when_arrays_have_different_lengths_simple(self, mock_replay_events):
        mock_replay_events.return_value.list_blocks.return_value = RecordingBlockListing(
            block_first_timestamps=[datetime(2024, 1, 1, 12, 0)],
            block_last_timestamps=[datetime(2024, 1, 1, 12, 1)],
            block_urls=[],  # Different length
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        blocks = list_blocks(self.recording)
        self.assertEqual(blocks, [])

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_list_blocks_returns_empty_list_when_arrays_have_different_lengths_complex(self, mock_replay_events):
        mock_replay_events.return_value.list_blocks.return_value = RecordingBlockListing(
            block_first_timestamps=[
                datetime(2024, 1, 1, 12, 0),
                datetime(2024, 1, 1, 12, 1),
                datetime(2024, 1, 1, 12, 2),
            ],
            block_last_timestamps=[
                datetime(2024, 1, 1, 12, 1),
                datetime(2024, 1, 1, 12, 2),
                datetime(2024, 1, 1, 12, 3),
                datetime(2024, 1, 1, 12, 4),  # Extra timestamp
            ],
            block_urls=[
                "s3://bucket/key1",
                "s3://bucket/key2",
                "s3://bucket/key3",
            ],
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        blocks = list_blocks(self.recording)
        self.assertEqual(blocks, [])

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_list_blocks_returns_empty_list_when_first_block_not_at_start_time(self, mock_replay_events):
        mock_replay_events.return_value.list_blocks.return_value = RecordingBlockListing(
            block_first_timestamps=[datetime(2024, 1, 1, 12, 1)],  # Later than start_time
            block_last_timestamps=[datetime(2024, 1, 1, 12, 2)],
            block_urls=["s3://bucket/key1"],
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        blocks = list_blocks(self.recording)
        self.assertEqual(blocks, [])

    @freeze_time("2024-01-02T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_list_blocks_returns_sorted_blocks(self, mock_replay_events):
        mock_replay_events.return_value.list_blocks.return_value = RecordingBlockListing(
            block_first_timestamps=[
                datetime(2024, 1, 1, 12, 0),
                datetime(2024, 1, 1, 12, 2),
                datetime(2024, 1, 1, 12, 1),
            ],
            block_last_timestamps=[
                datetime(2024, 1, 1, 12, 1),
                datetime(2024, 1, 1, 12, 3),
                datetime(2024, 1, 1, 12, 2),
            ],
            block_urls=[
                "s3://bucket/key1",
                "s3://bucket/key2",
                "s3://bucket/key3",
            ],
            start_time=datetime(2024, 1, 1, 12, 0),
        )

        blocks = list_blocks(self.recording)

        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].start_time, datetime(2024, 1, 1, 12, 0))
        self.assertEqual(blocks[1].start_time, datetime(2024, 1, 1, 12, 1))
        self.assertEqual(blocks[2].start_time, datetime(2024, 1, 1, 12, 2))
        self.assertEqual(blocks[0].url, "s3://bucket/key1")
        self.assertEqual(blocks[1].url, "s3://bucket/key3")
        self.assertEqual(blocks[2].url, "s3://bucket/key2")

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_load_blocks_does_not_cache_when_no_blocks_found(self, mock_replay_events, mock_cache):
        mock_cache.get.return_value = None
        mock_replay_events.return_value.list_blocks.return_value = None

        result = load_blocks(self.recording)

        self.assertIsNone(result)
        mock_cache.set.assert_not_called()

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_load_blocks_caches_with_short_timeout_for_recent_recording(self, mock_replay_events, mock_cache):
        mock_cache.get.return_value = None
        mock_blocks = RecordingBlockListing(
            block_first_timestamps=[datetime(2024, 1, 1, 12, 0)],
            block_last_timestamps=[datetime(2024, 1, 1, 12, 1)],
            block_urls=["s3://bucket/key1"],
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        mock_replay_events.return_value.list_blocks.return_value = mock_blocks

        result = load_blocks(self.recording)

        self.assertEqual(result, mock_blocks)
        expected_cache_key = f"recording_block_listing_{self.team.id}_{self.recording.session_id}"
        mock_cache.set.assert_called_once_with(expected_cache_key, mock_blocks, timeout=FIVE_SECONDS)

    @freeze_time("2024-01-02T13:00:00Z")  # More than 24 hours after recording start
    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_load_blocks_caches_with_long_timeout_for_old_recording(self, mock_replay_events, mock_cache):
        mock_cache.get.return_value = None
        mock_blocks = RecordingBlockListing(
            block_first_timestamps=[datetime(2024, 1, 1, 12, 0)],
            block_last_timestamps=[datetime(2024, 1, 1, 12, 1)],
            block_urls=["s3://bucket/key1"],
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        mock_replay_events.return_value.list_blocks.return_value = mock_blocks

        result = load_blocks(self.recording)

        self.assertEqual(result, mock_blocks)
        expected_cache_key = f"recording_block_listing_{self.team.id}_{self.recording.session_id}"
        mock_cache.set.assert_called_once_with(expected_cache_key, mock_blocks, timeout=ONE_DAY_IN_SECONDS)

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.session_recordings.session_recording_v2_service.cache")
    @patch("posthog.session_recordings.session_recording_v2_service.SessionReplayEvents")
    def test_load_blocks_returns_cached_data_without_calling_list_blocks(self, mock_replay_events, mock_cache):
        cached_blocks = RecordingBlockListing(
            block_first_timestamps=[datetime(2024, 1, 1, 12, 0)],
            block_last_timestamps=[datetime(2024, 1, 1, 12, 1)],
            block_urls=["s3://bucket/key1"],
            start_time=datetime(2024, 1, 1, 12, 0),
        )
        mock_cache.get.return_value = cached_blocks

        result = load_blocks(self.recording)

        self.assertEqual(result, cached_blocks)
        expected_cache_key = f"recording_block_listing_{self.team.id}_{self.recording.session_id}"
        mock_cache.get.assert_called_once_with(expected_cache_key)
        mock_replay_events.return_value.list_blocks.assert_not_called()
        mock_cache.set.assert_not_called()
