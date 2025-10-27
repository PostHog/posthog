from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, PersonalAPIKey, SessionRecording
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestSessionRecordingSnapshotsAPI(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()
        Person.objects.all().delete()

    def produce_replay_summary(
        self,
        distinct_id,
        session_id,
        timestamp,
        team_id=None,
    ):
        if team_id is None:
            team_id = self.team.pk

        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            ensure_analytics_event_in_session=False,
        )

    @parameterized.expand(
        [
            ("blob_v2", status.HTTP_400_BAD_REQUEST),  # 400 because blob_v2 requires blob keys
            (None, status.HTTP_200_OK),  # No source parameter
            ("invalid_source", status.HTTP_400_BAD_REQUEST),
            ("", status.HTTP_400_BAD_REQUEST),
            ("BLOB_V2", status.HTTP_400_BAD_REQUEST),  # Case-sensitive
        ]
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_snapshots_source_parameter_validation(
        self,
        source,
        expected_status,
        mock_list_objects,
        mock_presigned_url,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        # Basic mocking for successful cases
        mock_list_objects.return_value = []
        mock_presigned_url.return_value = None

        if source is not None:
            url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source={source}"
        else:
            url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/"

        response = self.client.get(url)
        assert (
            response.status_code == expected_status
        ), f"Expected {expected_status}, got {response.status_code}: {response.json()}"

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.async_client")
    def test_blob_v2_with_blob_keys_works(
        self,
        mock_async_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        """Test that blob_v2 with blob_keys parameter works correctly"""
        session_id = str(uuid7())

        # Mock the session recording
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        # Mock blocks - need at least 3 blocks for our test
        mock_blocks = [
            MagicMock(url="http://test.com/block0"),
            MagicMock(url="http://test.com/block1"),
            MagicMock(url="http://test.com/block2"),
        ]
        mock_list_blocks.return_value = mock_blocks

        # Mock the async client context manager
        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                '{"timestamp": 1000, "type": "snapshot1"}',
                '{"timestamp": 2000, "type": "snapshot2"}',
            ]
        )
        mock_async_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("content-type") == "application/jsonl"

        # Verify the client was called with correct block URLs
        assert mock_storage.fetch_block.call_count == 2
        mock_storage.fetch_block.assert_any_await("http://test.com/block0")
        mock_storage.fetch_block.assert_any_await("http://test.com/block1")

    @parameterized.expand(
        [
            ("0", "", ""),
            ("", "1", "Must provide either a blob key or start and end blob keys"),
        ]
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    def test_blob_v2_must_send_end_key_if_sending_start_key(
        self,
        start_key,
        end_key,
        expected_error_message,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)
        mock_list_blocks.return_value = [MagicMock(url="http://test.com/block0")]

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key={start_key}&end_blob_key={end_key}"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Must provide both start_blob_key and end_blob_key" in response.json()["detail"]

    @parameterized.expand(
        [(0, "a"), ("a", 1)],
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_with_non_integer_blob_keys_returns_400(
        self,
        start_key,
        end_key,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key={start_key}&end_blob_key={end_key}"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Blob key must be an integer" in response.json()["detail"]

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_with_too_many_blob_keys_returns_400(
        self,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        """Test that requesting more than 100 blob keys returns 400"""
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=12&end_blob_key=113"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot request more than 100 blob keys" in response.json()["detail"]

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_personal_api_key_cannot_request_more_than_20_blob_keys(
        self,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scopes=["session_recording:read"],
            scoped_teams=[self.team.pk],
        )

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=12&end_blob_key=33"

        response = self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {personal_api_key}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Cannot request more than 20 blob keys at once" in response.json()["detail"]

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_cannot_provide_both_blob_key_and_blob_keys(
        self,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        """Test that providing both blob_key and blob_keys returns 400"""
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&blob_key=0&start_blob_key=1"

        # Attempting to provide both blob_key and start_blob_key
        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Must provide a single blob key or start and end blob keys, not both" in response.json()["detail"]

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    def test_blob_v2_block_index_out_of_range_returns_404(
        self,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        """Test that requesting block indices out of range returns 404"""
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        # Mock only 2 blocks available (indices 0 and 1)
        mock_blocks = [
            MagicMock(url="http://test.com/block0"),
            MagicMock(url="http://test.com/block1"),
        ]
        mock_list_blocks.return_value = mock_blocks

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=3"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Block index out of range" in response.json()["detail"]

    @freeze_time("2023-01-01T00:00:00Z")
    @patch(
        "posthog.session_recordings.session_recording_api.list_blocks",
        side_effect=Exception(
            "if the LTS loading works then we'll not call list_blocks, we throw in the mock to enforce this"
        ),
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_sources_blobby_v2_from_lts(
        self,
        _mock_feature_enabled: MagicMock,
        mock_list_objects: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            storage_version="2023-08-01",
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        def list_objects_func(path: str) -> list[str]:
            # we're not expecting to call this, since we know all the data in the stored path
            raise Exception("we should not call list_objects for the LTS path")

        mock_list_objects.side_effect = list_objects_func

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?blob_v2=true&blob_v2_lts=true"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob_v2",
                    "blob_key": "the_lts_path/the_session_uuid",
                    # it's ok for these to be None, since we don't use the data anyway
                    # and this key is the whole session
                    "start_timestamp": None,
                    "end_timestamp": None,
                },
            ]
        }

    @freeze_time("2023-01-01T00:00:00Z")
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.client")
    @patch(
        "posthog.session_recordings.session_recording_api.list_blocks",
        side_effect=Exception(
            "if the LTS loading works then we'll not call list_blocks, we throw in the mock to enforce this"
        ),
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch(
        "posthog.session_recordings.session_recording_api.object_storage.list_objects",
        side_effect=Exception(
            "if the LTS loading works then we'll not call list_objects, we throw in the mock to enforce this"
        ),
    )
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_for_lts_source_blobby_v2(
        self,
        _mock_feature_enabled: MagicMock,
        _mock_list_objects: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
        mock_object_storage_client: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        # Mock the client fetch_block method
        mock_client_instance = MagicMock()
        mock_object_storage_client.return_value = mock_client_instance
        mock_client_instance.fetch_block.side_effect = Exception(
            "if the LTS loading works then we'll not call fetch_block, we throw in the mock to enforce this"
        )
        mock_client_instance.fetch_file.return_value = """
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            storage_version="2023-08-01",
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?blob_v2=true&blob_v2_lts=true&source=blob_v2&blob_key=/the_lts_path/the_session_uuid"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert (
            response.content
            == b"""
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """
        )

    @parameterized.expand(
        [
            (True, "application/jsonl", 2, 0),
            (False, "application/octet-stream", 0, 2),
        ]
    )
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.async_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_parameter(
        self,
        decompress,
        expected_content_type,
        expected_fetch_block_calls,
        expected_fetch_block_bytes_calls,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_async_client,
    ) -> None:
        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            MagicMock(url="http://test.com/block0"),
            MagicMock(url="http://test.com/block1"),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(side_effect=[test_data_1, test_data_2])
        mock_storage.fetch_block_bytes = AsyncMock(side_effect=[compressed_data_1, compressed_data_2])
        mock_async_client.return_value.__aenter__.return_value = mock_storage

        decompress_param = f"&decompress={str(decompress).lower()}"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1{decompress_param}"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.headers.get("content-type") == expected_content_type
        assert mock_storage.fetch_block.call_count == expected_fetch_block_calls
        assert mock_storage.fetch_block_bytes.call_count == expected_fetch_block_bytes_calls

    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.async_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_defaults_to_true(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_async_client,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [MagicMock(url="http://test.com/block0")]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(return_value='{"timestamp": 1000, "type": "snapshot1"}')
        mock_storage.fetch_block_bytes = AsyncMock()
        mock_async_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        assert mock_storage.fetch_block.call_count == 1
        assert mock_storage.fetch_block_bytes.call_count == 0

    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.async_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_false_returns_length_prefixed_format(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_async_client,
    ) -> None:
        """Test that decompress=false returns proper length-prefixed binary format"""
        import struct

        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            MagicMock(url="http://test.com/block0"),
            MagicMock(url="http://test.com/block1"),
            MagicMock(url="http://test.com/block2"),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        test_data_3 = '{"timestamp": 3000, "type": "snapshot3"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))
        compressed_data_3 = snappy.compress(test_data_3.encode("utf-8"))

        mock_storage = MagicMock()
        mock_storage.fetch_block_bytes = AsyncMock(
            side_effect=[compressed_data_1, compressed_data_2, compressed_data_3]
        )
        mock_async_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=2&decompress=false"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("content-type") == "application/octet-stream"

        response_bytes = response.content
        offset = 0

        block_1_length = struct.unpack(">I", response_bytes[offset : offset + 4])[0]
        offset += 4
        assert block_1_length == len(compressed_data_1)

        block_1_data = response_bytes[offset : offset + block_1_length]
        offset += block_1_length
        assert block_1_data == compressed_data_1
        assert snappy.decompress(block_1_data).decode("utf-8") == test_data_1

        block_2_length = struct.unpack(">I", response_bytes[offset : offset + 4])[0]
        offset += 4
        assert block_2_length == len(compressed_data_2)

        block_2_data = response_bytes[offset : offset + block_2_length]
        offset += block_2_length
        assert block_2_data == compressed_data_2
        assert snappy.decompress(block_2_data).decode("utf-8") == test_data_2

        block_3_length = struct.unpack(">I", response_bytes[offset : offset + 4])[0]
        offset += 4
        assert block_3_length == len(compressed_data_3)

        block_3_data = response_bytes[offset : offset + block_3_length]
        offset += block_3_length
        assert block_3_data == compressed_data_3
        assert snappy.decompress(block_3_data).decode("utf-8") == test_data_3

        assert offset == len(response_bytes)
