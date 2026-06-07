from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, PersonalAPIKey, SessionRecording
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.recordings.errors import (
    BlockFetchClientError,
    BlockNotFoundError,
    RecordingDeletedError,
    TransientBlockFetchError,
)
from posthog.session_recordings.session_recording_v2_service import RecordingBlock


class TestSessionRecordingSnapshotsAPI(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()
        Person.objects.filter(team_id__isnull=False).delete()

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
    def test_snapshots_source_parameter_validation(
        self,
        source,
        expected_status,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        if source is not None:
            url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source={source}"
        else:
            url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/"

        response = self.client.get(url)
        assert response.status_code == expected_status, (
            f"Expected {expected_status}, got {response.status_code}: {response.json()}"
        )

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_with_blob_keys_works(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
            RecordingBlock(
                key="key2",
                start_byte=201,
                end_byte=300,
                start_timestamp="2024-01-01T00:02:00Z",
                end_timestamp="2024-01-01T00:03:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                b'{"timestamp": 1000, "type": "snapshot1"}',
                b'{"timestamp": 2000, "type": "snapshot2"}',
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("content-type") == "application/jsonl"

        assert mock_storage.fetch_block.call_count == 2
        call_args_list = mock_storage.fetch_block.await_args_list
        assert call_args_list[0].args == ("key0", 0, 100, session_id, self.team.id)
        assert call_args_list[0].kwargs.get("decompress") is True
        assert call_args_list[1].args == ("key1", 101, 200, session_id, self.team.id)
        assert call_args_list[1].kwargs.get("decompress") is True

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_block_fetch_failure_returns_retriable_503(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]

        mock_storage = MagicMock()
        # The second block fails to fetch (recording-api error / timeout / S3 failure).
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                b'{"timestamp": 1000, "type": "snapshot1"}',
                TransientBlockFetchError("upstream recording-api returned 502"),
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)

        # A transient block-fetch failure must be a retriable 503, never a blanket 500.
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.json()
        assert response.json()["error"] == "Failed to load recording block. Please try again later."

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_block_not_found_returns_terminal_404(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]

        mock_storage = MagicMock()
        # The second block is permanently gone (recording-api 404), not a transient failure.
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                b'{"timestamp": 1000, "type": "snapshot1"}',
                BlockNotFoundError("Block not found"),
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)

        # A permanently-missing block is terminal — a non-retriable 404, never a retriable 503.
        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert response.json()["error"] == "A recording block could not be found."

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_backoff_returns_429_with_retry_after(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
        ]

        mock_storage = MagicMock()
        # The recording-api asked us to back off longer than we'll wait inline.
        mock_storage.fetch_block = AsyncMock(
            side_effect=BlockFetchClientError("Recording API returned 429", status_code=429, retry_after="60")
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        response = self.client.get(url)

        # The back-off is handed to the client as a 429 + Retry-After, not retried server-side.
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.json()
        assert response["Retry-After"] == "60"

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_client_error_returned_as_is(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
        ]

        mock_storage = MagicMock()
        # A non-retriable upstream client error (e.g. 403) — returned to the client as that status.
        mock_storage.fetch_block = AsyncMock(
            side_effect=BlockFetchClientError("Recording API returned 403", status_code=403)
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        response = self.client.get(url)

        # Returned as its own status, not masked as a retriable 503, and no Retry-After.
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert "Retry-After" not in response

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_not_found_takes_precedence_over_transient(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]

        mock_storage = MagicMock()
        # One block fails transiently while another is permanently gone — the terminal
        # not-found must win, so the request is a non-retriable 404 rather than a 503.
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                TransientBlockFetchError("upstream recording-api returned 502"),
                BlockNotFoundError("Block not found"),
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
        assert response.json()["error"] == "A recording block could not be found."

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
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
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
        mock_list_blocks.return_value = [
            RecordingBlock(
                key="block0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key={start_key}&end_blob_key={end_key}"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Must provide both start blob key and end blob key" in response.json()["detail"]

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
        assert "Blob keys must be integers" in response.json()["detail"]

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

        response = self.client.get(url, headers={"authorization": f"Bearer {personal_api_key}"})
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
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&blob_key=0&start_blob_key=1"

        # Attempting to provide both blob_key and start_blob_key
        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Must provide both start blob key and end blob key" in response.json()["detail"]

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    def test_blob_v2_block_index_out_of_range_returns_404(
        self,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        # Mock only 2 blocks available (indices 0 and 1)
        mock_blocks = [
            RecordingBlock(
                key="block0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="block1",
                start_byte=0,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
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
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_sources_blobby_v2_from_lts(
        self,
        _mock_feature_enabled: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob_v2_lts",
                    "blob_key": "the_lts_path/the_session_uuid",
                    # it's ok for these to be None, since we don't use the data anyway
                    # and this key is the whole session
                    "start_timestamp": None,
                    "end_timestamp": None,
                },
            ]
        }

    @freeze_time("2023-01-01T00:00:00Z")
    @patch("posthog.session_recordings.session_recording_api.recording_s3_client.recording_s3_client")
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
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_for_lts_source_blobby_v2(
        self,
        _mock_feature_enabled: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
        mock_object_storage_client: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        mock_client_instance = MagicMock()
        mock_object_storage_client.return_value = mock_client_instance
        mock_client_instance.download_file_decompressed.return_value = """
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?source=blob_v2_lts&blob_key=/the_lts_path/the_session_uuid"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert (
            response.content
            == b"""
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """
        )

    @freeze_time("2023-01-01T00:00:00Z")
    @patch("posthog.session_recordings.session_recording_api.recording_s3_client.recording_s3_client")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    def test_cannot_load_lts_data_for_different_session(
        self,
        _mock_exists: MagicMock,
        mock_object_storage_client: MagicMock,
    ) -> None:
        session_a = str(uuid7())
        session_b = str(uuid7())

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_a,
            deleted=False,
            full_recording_v2_path="s3://the_bucket/lts_path/session_a_uuid?range=0-1000",
        )

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_b,
            deleted=False,
            full_recording_v2_path="s3://the_bucket/lts_path/session_b_uuid?range=0-2000",
        )

        mock_client_instance = MagicMock()
        mock_object_storage_client.return_value = mock_client_instance
        mock_client_instance.download_file_decompressed.return_value = '{"timestamp": 9999, "type": "session_b_data"}'

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_a}/snapshots"
            f"?source=blob_v2_lts&blob_key=lts_path/session_b_uuid"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            (True, "application/jsonl"),
            (False, "application/octet-stream"),
        ]
    )
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_parameter(
        self,
        decompress,
        expected_content_type,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ) -> None:
        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))

        mock_storage = MagicMock()
        if decompress:
            mock_storage.fetch_block = AsyncMock(side_effect=[test_data_1.encode(), test_data_2.encode()])
        else:
            mock_storage.fetch_block = AsyncMock(side_effect=[compressed_data_1, compressed_data_2])
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        decompress_param = f"&decompress={str(decompress).lower()}"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1{decompress_param}"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.headers.get("content-type") == expected_content_type
        assert mock_storage.fetch_block.call_count == 2
        for call in mock_storage.fetch_block.await_args_list:
            assert call.kwargs["decompress"] == decompress

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
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
        mock_recording_api_client,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(return_value=b'{"timestamp": 1000, "type": "snapshot1"}')
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        assert mock_storage.fetch_block.call_count == 1
        assert mock_storage.fetch_block.await_args.kwargs["decompress"] is True

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompressed_blocks_with_trailing_newlines_concatenate_cleanly(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ) -> None:
        session_id = str(uuid7())
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                b'{"timestamp": 1000}\n{"timestamp": 2000}\n',
                b'{"timestamp": 3000}\n{"timestamp": 4000}\n',
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.content == b'{"timestamp": 1000}\n{"timestamp": 2000}\n{"timestamp": 3000}\n{"timestamp": 4000}'

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
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
        mock_recording_api_client,
    ) -> None:
        import struct

        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
            RecordingBlock(
                key="key2",
                start_byte=201,
                end_byte=300,
                start_timestamp="2024-01-01T00:02:00Z",
                end_timestamp="2024-01-01T00:03:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        test_data_3 = '{"timestamp": 3000, "type": "snapshot3"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))
        compressed_data_3 = snappy.compress(test_data_3.encode("utf-8"))

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(side_effect=[compressed_data_1, compressed_data_2, compressed_data_3])
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

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

    # Tests for Recording API path (recording_api_client)

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    def test_blob_v2_with_blob_keys_works_via_recording_api(
        self,
        mock_recording_api_client,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
            RecordingBlock(
                key="key2",
                start_byte=201,
                end_byte=300,
                start_timestamp="2024-01-01T00:02:00Z",
                end_timestamp="2024-01-01T00:03:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(
            side_effect=[
                b'{"timestamp": 1000, "type": "snapshot1"}',
                b'{"timestamp": 2000, "type": "snapshot2"}',
            ]
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("content-type") == "application/jsonl"

        assert mock_storage.fetch_block.call_count == 2
        call_args_list = mock_storage.fetch_block.await_args_list
        assert call_args_list[0].args == ("key0", 0, 100, session_id, self.team.id)
        assert call_args_list[0].kwargs.get("decompress") is True
        assert call_args_list[1].args == ("key1", 101, 200, session_id, self.team.id)
        assert call_args_list[1].kwargs.get("decompress") is True

    @parameterized.expand(
        [
            (True, "application/jsonl"),
            (False, "application/octet-stream"),
        ]
    )
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_parameter_via_recording_api(
        self,
        decompress,
        expected_content_type,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ) -> None:
        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))

        mock_storage = MagicMock()
        if decompress:
            mock_storage.fetch_block = AsyncMock(side_effect=[test_data_1.encode(), test_data_2.encode()])
        else:
            mock_storage.fetch_block = AsyncMock(side_effect=[compressed_data_1, compressed_data_2])
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        decompress_param = f"&decompress={str(decompress).lower()}"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1{decompress_param}"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.headers.get("content-type") == expected_content_type
        assert mock_storage.fetch_block.call_count == 2
        for call in mock_storage.fetch_block.await_args_list:
            assert call.kwargs["decompress"] == decompress

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_defaults_to_true_via_recording_api(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ) -> None:
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]
        mock_list_blocks.return_value = mock_blocks

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(return_value=b'{"timestamp": 1000, "type": "snapshot1"}')
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        assert mock_storage.fetch_block.call_count == 1
        assert mock_storage.fetch_block.await_args.kwargs["decompress"] is True

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_decompress_false_returns_length_prefixed_format_via_recording_api(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ) -> None:
        import struct

        import snappy

        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_blocks = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            ),
            RecordingBlock(
                key="key1",
                start_byte=101,
                end_byte=200,
                start_timestamp="2024-01-01T00:01:00Z",
                end_timestamp="2024-01-01T00:02:00Z",
            ),
            RecordingBlock(
                key="key2",
                start_byte=201,
                end_byte=300,
                start_timestamp="2024-01-01T00:02:00Z",
                end_timestamp="2024-01-01T00:03:00Z",
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        test_data_1 = '{"timestamp": 1000, "type": "snapshot1"}'
        test_data_2 = '{"timestamp": 2000, "type": "snapshot2"}'
        test_data_3 = '{"timestamp": 3000, "type": "snapshot3"}'
        compressed_data_1 = snappy.compress(test_data_1.encode("utf-8"))
        compressed_data_2 = snappy.compress(test_data_2.encode("utf-8"))
        compressed_data_3 = snappy.compress(test_data_3.encode("utf-8"))

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(side_effect=[compressed_data_1, compressed_data_2, compressed_data_3])
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

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

    # Tests for 410 Gone response when recording is deleted

    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_returns_410_when_recording_deleted(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
    ):
        session_id = str(uuid7())

        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_list_blocks.return_value = [
            RecordingBlock(
                key="key0",
                start_byte=0,
                end_byte=100,
                start_timestamp="2024-01-01T00:00:00Z",
                end_timestamp="2024-01-01T00:01:00Z",
            )
        ]

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(
            side_effect=RecordingDeletedError("recording deleted", deleted_at=1700000000)
        )
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_410_GONE
        assert response.json()["error"] == "recording_deleted"
        assert response.json()["deleted_at"] == 1700000000
