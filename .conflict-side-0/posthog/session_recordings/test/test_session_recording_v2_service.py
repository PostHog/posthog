from datetime import datetime

from freezegun import freeze_time
from unittest.mock import Mock, patch

from django.test import TestCase

from posthog.session_recordings.models.metadata import RecordingBlockListing
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import (
    FIVE_SECONDS,
    RecordingBlock,
    copy_to_lts,
    list_blocks,
    listing_cache_key,
    load_blocks,
)
from posthog.storage.session_recording_v2_object_storage import BlockFetchError


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
        expected_cache_key = listing_cache_key(self.recording)
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
        expected_cache_key = listing_cache_key(self.recording)
        # cache is forced to 5 seconds always
        mock_cache.set.assert_called_once_with(expected_cache_key, mock_blocks, timeout=FIVE_SECONDS)

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
        expected_cache_key = listing_cache_key(self.recording)
        mock_cache.get.assert_called_once_with(expected_cache_key)
        mock_replay_events.return_value.list_blocks.assert_not_called()
        mock_cache.set.assert_not_called()


class TestCopyToLTS(TestCase):
    def setUp(self):
        self.team = Mock(id=1)
        self.recording = Mock(spec=SessionRecording)
        self.recording.session_id = "test_recording_id"
        self.recording.team = self.team
        self.recording.team_id = 1

        # Sample test data
        self.block1_events = (
            '{"timestamp":1,"type":2,"data":{"href":"http://localhost:3000/","width":2560,"height":1304}}\n'
            '{"timestamp":2,"type":3,"data":{"source":0,"positions":[{"x":127,"y":312,"id":475,"timeOffset":0}]}}'
        )
        self.block2_events = (
            '{"timestamp":1000,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":0}]}}\n'
            '{"timestamp":1001,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":100}]}}'
        )

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_success(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup blocks
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0),
                end_time=datetime(2024, 1, 1, 12, 1),
                url="s3://bucket/block1",
            ),
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 1),
                end_time=datetime(2024, 1, 1, 12, 2),
                url="s3://bucket/block2",
            ),
        ]

        # Mock fetch_block responses
        mock_client.fetch_block.side_effect = [self.block1_events, self.block2_events]

        # Mock store_lts_recording success
        mock_client.store_lts_recording.return_value = ("s3://bucket/lts/test_recording_id", None)

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertEqual(result, "s3://bucket/lts/test_recording_id")
        mock_client.fetch_block.assert_any_call("s3://bucket/block1")
        mock_client.fetch_block.assert_any_call("s3://bucket/block2")

        # Check that blocks were concatenated with newlines
        expected_data = f"{self.block1_events}\n{self.block2_events}"
        mock_client.store_lts_recording.assert_called_once_with("test_recording_id", expected_data)

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_storage_disabled(self, mock_list_blocks, mock_storage):
        # Setup storage client as disabled
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = False
        mock_client.is_lts_enabled.return_value = True

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertIsNone(result)
        mock_list_blocks.assert_not_called()
        mock_client.fetch_block.assert_not_called()
        mock_client.store_lts_recording.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_lts_disabled(self, mock_list_blocks, mock_storage):
        # Setup storage client with LTS disabled
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = False

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertIsNone(result)
        mock_list_blocks.assert_not_called()
        mock_client.fetch_block.assert_not_called()
        mock_client.store_lts_recording.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_no_blocks(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # No blocks returned
        mock_list_blocks.return_value = []

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertIsNone(result)
        mock_client.fetch_block.assert_not_called()
        mock_client.store_lts_recording.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_block_fetch_error(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup one block
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0),
                end_time=datetime(2024, 1, 1, 12, 1),
                url="s3://bucket/block1",
            ),
        ]

        # Mock fetch_block to raise error
        mock_client.fetch_block.side_effect = BlockFetchError("Failed to fetch block")

        # Execute and expect exception
        with self.assertRaises(BlockFetchError):
            copy_to_lts(self.recording)

        # Assert
        mock_client.fetch_block.assert_called_once_with("s3://bucket/block1")
        mock_client.store_lts_recording.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_partial_fetch_error(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup two blocks
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0),
                end_time=datetime(2024, 1, 1, 12, 1),
                url="s3://bucket/block1",
            ),
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 1),
                end_time=datetime(2024, 1, 1, 12, 2),
                url="s3://bucket/block2",
            ),
        ]

        # Mock fetch_block to succeed for first block, fail for second
        mock_client.fetch_block.side_effect = [self.block1_events, BlockFetchError("Failed to fetch block2")]

        # Execute and expect exception
        with self.assertRaises(BlockFetchError):
            copy_to_lts(self.recording)

        # Assert - should have tried to fetch both blocks
        self.assertEqual(mock_client.fetch_block.call_count, 2)
        mock_client.store_lts_recording.assert_not_called()

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_store_error(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup one block
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0),
                end_time=datetime(2024, 1, 1, 12, 1),
                url="s3://bucket/block1",
            ),
        ]

        # Mock fetch_block success
        mock_client.fetch_block.return_value = self.block1_events

        # Mock store_lts_recording failure
        mock_client.store_lts_recording.return_value = (None, "Storage error")

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertIsNone(result)
        mock_client.fetch_block.assert_called_once_with("s3://bucket/block1")
        mock_client.store_lts_recording.assert_called_once_with("test_recording_id", self.block1_events)

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_single_block(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup single block
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0),
                end_time=datetime(2024, 1, 1, 12, 1),
                url="s3://bucket/block1",
            ),
        ]

        # Mock fetch_block response
        mock_client.fetch_block.return_value = self.block1_events

        # Mock store_lts_recording success
        mock_client.store_lts_recording.return_value = ("s3://bucket/lts/test_recording_id", None)

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertEqual(result, "s3://bucket/lts/test_recording_id")
        mock_client.fetch_block.assert_called_once_with("s3://bucket/block1")
        # For single block, no additional newlines should be added
        mock_client.store_lts_recording.assert_called_once_with("test_recording_id", self.block1_events)

    @patch("posthog.session_recordings.session_recording_v2_service.session_recording_v2_object_storage")
    @patch("posthog.session_recordings.session_recording_v2_service.list_blocks")
    def test_copy_to_lts_multiple_blocks_concatenation(self, mock_list_blocks, mock_storage):
        # Setup storage client
        mock_client = Mock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Setup three blocks
        block3_events = '{"timestamp":2000,"type":4,"data":{"x":100,"y":200}}'
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 0), end_time=datetime(2024, 1, 1, 12, 1), url="s3://bucket/block1"
            ),
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 1), end_time=datetime(2024, 1, 1, 12, 2), url="s3://bucket/block2"
            ),
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 12, 2), end_time=datetime(2024, 1, 1, 12, 3), url="s3://bucket/block3"
            ),
        ]

        # Mock fetch_block responses
        mock_client.fetch_block.side_effect = [self.block1_events, self.block2_events, block3_events]

        # Mock store_lts_recording success
        mock_client.store_lts_recording.return_value = ("s3://bucket/lts/test_recording_id", None)

        # Execute
        result = copy_to_lts(self.recording)

        # Assert
        self.assertEqual(result, "s3://bucket/lts/test_recording_id")
        self.assertEqual(mock_client.fetch_block.call_count, 3)

        # Check that blocks were concatenated properly with newlines
        expected_data = f"{self.block1_events}\n{self.block2_events}\n{block3_events}"
        mock_client.store_lts_recording.assert_called_once_with("test_recording_id", expected_data)
