import datetime
from unittest.mock import MagicMock, patch

from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, SessionRecording, PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, uuid7
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.session_recording_v2_service import RecordingBlock
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
)


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

    @freeze_time("2023-01-01T00:00:00Z")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    def test_get_snapshots_v2_listing_sources(self, mock_list_blocks: MagicMock, _mock_exists: MagicMock) -> None:
        session_id = str(uuid7())

        # Mock blocks - need at least 3 blocks for our test
        mock_blocks: list[RecordingBlock] = [
            RecordingBlock(
                url="http://test.com/block0",
                start_time=datetime.datetime.fromisoformat("2022-12-31T23:59:50Z"),
                end_time=datetime.datetime.fromisoformat("2022-12-31T00:00:05Z"),
            ),
            RecordingBlock(
                url="http://test.com/block1",
                start_time=datetime.datetime.fromisoformat("2022-12-31T23:59:55Z"),
                end_time=datetime.datetime.fromisoformat("2023-01-01T00:00:00Z"),
            ),
        ]
        mock_list_blocks.return_value = mock_blocks

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob_v2",
                    "start_timestamp": "2022-12-31T23:59:50Z",
                    "end_timestamp": "2022-12-31T00:00:05Z",
                    "blob_key": "0",
                },
                {
                    "source": "blob_v2",
                    "start_timestamp": "2022-12-31T23:59:55Z",
                    "end_timestamp": "2023-01-01T00:00:00Z",
                    "blob_key": "1",
                },
            ]
        }

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
        assert (
            response.status_code == expected_status
        ), f"Expected {expected_status}, got {response.status_code}: {response.json()}"

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.client")
    def test_blob_v2_with_blob_keys_works(
        self,
        mock_client,
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

        # Mock the client fetch_block method
        mock_client_instance = MagicMock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.fetch_block.side_effect = [
            '{"timestamp": 1000, "type": "snapshot1"}',
            '{"timestamp": 2000, "type": "snapshot2"}',
        ]

        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=1"

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("content-type") == "application/jsonl"

        # Verify the client was called with correct block URLs
        assert mock_client_instance.fetch_block.call_count == 2
        mock_client_instance.fetch_block.assert_any_call("http://test.com/block0")
        mock_client_instance.fetch_block.assert_any_call("http://test.com/block1")

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
