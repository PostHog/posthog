from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from ee.session_recordings.session_recording_extensions import persist_recording_v2
from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.storage.session_recording_v2_object_storage import BlockFetchError

BLOCK1_EVENTS = (
    '{"timestamp":1,"type":2,"data":{"href":"http://localhost:3000/","width":2560,"height":1304}}\n'
    '{"timestamp":2,"type":3,"data":{"source":0,"positions":[{"x":127,"y":312,"id":475,"timeOffset":0}]}}'
)

BLOCK2_EVENTS = (
    '{"timestamp":1000,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":0}]}}\n'
    '{"timestamp":1001,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":100}]}}'
)


class TestSessionRecordingExtensions(TestCase):
    @patch("ee.session_recordings.session_recording_extensions.SessionRecording")
    @patch("ee.session_recordings.session_recording_extensions.list_blocks")
    @patch("ee.session_recordings.session_recording_extensions.session_recording_v2_object_storage")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_success(self, mock_storage, mock_list_blocks, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Setup storage client
        mock_client = MagicMock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Mock list_blocks to return two blocks
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 11, 0),
                end_time=datetime(2024, 1, 1, 11, 1),
                url="s3://bucket/block1",
            ),
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 11, 1),
                end_time=datetime(2024, 1, 1, 11, 2),
                url="s3://bucket/block2",
            ),
        ]

        # Mock fetch_block to return events for each block
        mock_client.fetch_block.side_effect = [BLOCK1_EVENTS, BLOCK2_EVENTS]

        # Mock store_lts_recording
        mock_client.store_lts_recording.return_value = ("s3://bucket/lts/test_id", None)

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_client.fetch_block.assert_any_call("s3://bucket/block1")
        mock_client.fetch_block.assert_any_call("s3://bucket/block2")

        # Check that blocks were concatenated with newlines
        expected_data = f"{BLOCK1_EVENTS}\n{BLOCK2_EVENTS}"
        mock_client.store_lts_recording.assert_called_once_with("test_id", expected_data)

        # Check that the recording was updated
        mock_recording.save.assert_called_once()
        self.assertEqual(mock_recording.full_recording_v2_path, "s3://bucket/lts/test_id")

    @patch("ee.session_recordings.session_recording_extensions.SessionRecording")
    @patch("ee.session_recordings.session_recording_extensions.list_blocks")
    @patch("ee.session_recordings.session_recording_extensions.session_recording_v2_object_storage")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_skips_if_too_young(self, mock_storage, mock_list_blocks, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=1)
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Setup storage client
        mock_client = MagicMock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_list_blocks.assert_not_called()
        mock_client.fetch_block.assert_not_called()
        mock_client.store_lts_recording.assert_not_called()
        mock_recording.save.assert_called_once()

    @patch("ee.session_recordings.session_recording_extensions.SessionRecording")
    @patch("ee.session_recordings.session_recording_extensions.list_blocks")
    @patch("ee.session_recordings.session_recording_extensions.session_recording_v2_object_storage")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_handles_block_fetch_error(self, mock_storage, mock_list_blocks, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Setup storage client
        mock_client = MagicMock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Mock list_blocks to return one block
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 11, 0),
                end_time=datetime(2024, 1, 1, 11, 1),
                url="s3://bucket/block1",
            )
        ]

        # Mock fetch_block to raise error
        mock_client.fetch_block.side_effect = BlockFetchError("Failed to fetch block")

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_client.fetch_block.assert_called_once_with("s3://bucket/block1")
        mock_client.store_lts_recording.assert_not_called()
        self.assertIsNone(mock_recording.full_recording_v2_path)

    @patch("ee.session_recordings.session_recording_extensions.SessionRecording")
    @patch("ee.session_recordings.session_recording_extensions.list_blocks")
    @patch("ee.session_recordings.session_recording_extensions.session_recording_v2_object_storage")
    @freeze_time("2024-01-01T12:00:00Z")
    def test_persist_recording_v2_handles_store_error(self, mock_storage, mock_list_blocks, mock_recording_model):
        # Setup mock recording
        mock_recording = MagicMock()
        mock_recording.session_id = "test_id"
        mock_recording.deleted = False
        mock_recording.start_time = timezone.now() - timedelta(hours=25)
        mock_recording.full_recording_v2_path = None
        mock_recording_model.objects.select_related.return_value.get.return_value = mock_recording

        # Setup storage client
        mock_client = MagicMock()
        mock_storage.client.return_value = mock_client
        mock_client.is_enabled.return_value = True
        mock_client.is_lts_enabled.return_value = True

        # Mock list_blocks to return one block
        mock_list_blocks.return_value = [
            RecordingBlock(
                start_time=datetime(2024, 1, 1, 11, 0),
                end_time=datetime(2024, 1, 1, 11, 1),
                url="s3://bucket/block1",
            )
        ]

        # Mock fetch_block to return sample events
        mock_client.fetch_block.return_value = BLOCK1_EVENTS

        # Mock store_lts_recording to return error
        mock_client.store_lts_recording.return_value = (None, "Failed to store")

        # Execute
        persist_recording_v2("test_id", 1)

        # Assert
        mock_client.fetch_block.assert_called_once()
        mock_client.store_lts_recording.assert_called_once()
        self.assertIsNone(mock_recording.full_recording_v2_path)
