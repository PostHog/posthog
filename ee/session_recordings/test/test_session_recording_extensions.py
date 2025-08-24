from datetime import UTC
from datetime import datetime, timedelta
from secrets import token_urlsafe
from unittest.mock import patch, MagicMock
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from django.utils import timezone
from freezegun import freeze_time

from ee.session_recordings.session_recording_extensions import (
    persist_recording,
)
from ee.session_recordings.session_recording_extensions import persist_recording_v2
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.settings import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
)
from posthog.storage.object_storage import write, list_objects, object_storage_client
from posthog.storage.session_recording_v2_object_storage import BlockFetchError
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

BLOCK1_EVENTS = (
    '{"timestamp":1,"type":2,"data":{"href":"http://localhost:3000/","width":2560,"height":1304}}\n'
    '{"timestamp":2,"type":3,"data":{"source":0,"positions":[{"x":127,"y":312,"id":475,"timeOffset":0}]}}'
)

BLOCK2_EVENTS = (
    '{"timestamp":1000,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":0}]}}\n'
    '{"timestamp":1001,"type":3,"data":{"source":1,"positions":[{"x":875,"y":243,"id":884,"timeOffset":100}]}}'
)

long_url = f"https://app.posthog.com/my-url?token={token_urlsafe(600)}"


TEST_BUCKET = "test_storage_bucket-TestSessionRecordingExtensions"


class TestSessionRecordingExtensions(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def test_does_not_persist_too_recent_recording(self):
        recording = SessionRecording.objects.create(
            team=self.team,
            session_id=f"test_does_not_persist_too_recent_recording-s1-{uuid4()}",
        )

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=recording.session_id,
            distinct_id="distinct_id_1",
            first_timestamp=recording.created_at,
            last_timestamp=recording.created_at,
        )
        persist_recording(recording.session_id, recording.team_id)
        recording.refresh_from_db()

        assert not recording.object_storage_path

    def test_can_build_object_storage_paths(self) -> None:
        produce_replay_summary(
            session_id="test_can_build_different_object_storage_paths-s1",
            team_id=self.team.pk,
        )

        recording: SessionRecording = SessionRecording.objects.create(
            team=self.team,
            session_id="test_can_build_different_object_storage_paths-s1",
        )

        assert (
            recording.build_blob_lts_storage_path("2023-08-01")
            == f"session_recordings_lts/team_id/{self.team.pk}/session_id/test_can_build_different_object_storage_paths-s1/data"
        )

    def test_persists_recording_from_blob_ingested_storage(self):
        with self.settings(OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET):
            two_minutes_ago = (datetime.now() - timedelta(minutes=2)).replace(tzinfo=UTC)

            with freeze_time(two_minutes_ago):
                session_id = f"test_persists_recording_from_blob_ingested_storage-s1-{uuid4()}"

                produce_replay_summary(
                    session_id=session_id,
                    team_id=self.team.pk,
                    first_timestamp=(two_minutes_ago - timedelta(hours=48)).isoformat(),
                    last_timestamp=(two_minutes_ago - timedelta(hours=46)).isoformat(),
                    distinct_id="distinct_id_1",
                    first_url="https://app.posthog.com/my-url",
                )

                # this recording already has several files stored from Mr. Blobby
                # these need to be written before creating the recording object
                blob_path = f"{TEST_BUCKET}/team_id/{self.team.pk}/session_id/{session_id}/data"
                for file in ["a", "b", "c"]:
                    file_name = f"{blob_path}/{file}"
                    write(file_name, f"my content-{file}".encode())

                assert object_storage_client().list_objects(OBJECT_STORAGE_BUCKET, blob_path) == [
                    f"{blob_path}/a",
                    f"{blob_path}/b",
                    f"{blob_path}/c",
                ]

                recording: SessionRecording = SessionRecording.objects.create(team=self.team, session_id=session_id)

                assert recording.created_at == two_minutes_ago
                assert recording.storage_version is None

            persist_recording(recording.session_id, recording.team_id)
            recording.refresh_from_db()

            assert (
                recording.object_storage_path
                == f"session_recordings_lts/team_id/{self.team.pk}/session_id/{recording.session_id}/data"
            )
            assert recording.start_time == recording.created_at - timedelta(hours=48)
            assert recording.end_time == recording.created_at - timedelta(hours=46)

            assert recording.storage_version == "2023-08-01"
            assert recording.distinct_id == "distinct_id_1"
            assert recording.duration == 7200
            assert recording.click_count == 0
            assert recording.keypress_count == 0
            assert recording.start_url == "https://app.posthog.com/my-url"

            stored_objects = list_objects(recording.build_blob_lts_storage_path("2023-08-01"))
            assert stored_objects == [
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/a",
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/b",
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/c",
            ]

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
