from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.auth import mint_export_renderer_token
from posthog.clickhouse.client import sync_execute
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models import PersonalAPIKey, SessionRecording, SharingConfiguration
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.recordings.errors import RecordingDeletedError
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, listing_cache_key

from products.exports.backend.models.exported_asset import ExportedAsset


class TestSessionRecordingSnapshotsAPI(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()

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

    @parameterized.expand(
        [
            ("logged_in", "session", True, True, True),
            ("logged_in_flag_off", "session", False, True, False),
            ("logged_in_unencrypted_recording", "session", True, False, False),
            ("personal_api_key", "personal_api_key", True, True, False),
            ("export_renderer", "export_renderer", True, True, True),
            ("share_link", "share_link", True, True, False),
        ]
    )
    @override_settings(
        REPLAY_PROXY_JWT_SECRET="replay-proxy-key",
        RECORDING_API_BLOCKS_JWT_SECRET="replay-blocks-key",
        CLOUD_DEPLOYMENT="DEV",
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.list_blocks")
    @patch("posthog.session_recordings.recordings.replay_blocks_jwt.posthoganalytics.feature_enabled")
    def test_sources_listing_gives_player_tokens_only_to_the_player(
        self,
        _name: str,
        auth: str,
        flag_on: bool,
        encrypted: bool,
        expects_block_urls: bool,
        mock_feature_enabled,
        mock_list_blocks,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)
        mock_feature_enabled.return_value = flag_on
        mock_list_blocks.return_value = [
            RecordingBlock(
                key=f"key{i}",
                start_byte=0,
                end_byte=10,
                start_timestamp=f"2026-01-01T00:00:0{i}Z",
                end_timestamp=f"2026-01-01T00:00:0{i}Z",
                ref=f"v1.ref{i}" if encrypted else None,
            )
            for i in range(2)
        ]
        is_player = auth != "personal_api_key"
        headers = {}
        query = ""
        viewer = f"u{self.user.pk}"
        if auth == "export_renderer":
            asset = ExportedAsset.objects.create(
                team=self.team,
                created_by=self.user,
                export_format=ExportedAsset.ExportFormat.PNG,
                export_context={"session_recording_id": session_id},
            )
            renderer_token = mint_export_renderer_token(
                user_id=self.user.id, team_id=self.team.id, exported_asset_id=asset.id, scope="session_recording:read"
            )
            headers = {"authorization": f"Bearer {renderer_token}"}
            viewer = f"e{self.team.pk}"
        if auth == "share_link":
            recording = SessionRecording.objects.create(session_id=session_id, team=self.team)
            sharing = SharingConfiguration.objects.create(team=self.team, recording=recording, enabled=True)
            mock_get_session_recording.return_value = recording
            query = f"?sharing_access_token={sharing.access_token}"
            self.client.logout()
        if auth == "personal_api_key":
            personal_api_key = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="Test Key",
                user=self.user,
                secure_value=hash_key_value(personal_api_key),
                scopes=["session_recording:read"],
                scoped_teams=[self.team.pk],
            )
            headers = {"authorization": f"Bearer {personal_api_key}"}

        response = self.client.get(
            f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/{query}", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        if is_player:
            claims = decode_jwt(
                body["replay_proxy_token"], PosthogJwtAudience.REPLAY_PROXY, verification_keys=["replay-proxy-key"]
            )
            assert claims["team_id"] == self.team.pk
        else:
            assert body["replay_proxy_token"] is None

        urls = [source.get("url") for source in body["sources"]]
        if expects_block_urls:
            assert urls == [f"/replay-blocks/{self.team.pk}/{session_id}/{viewer}/v1.ref{i}" for i in range(2)]
            claims = decode_jwt(
                body["block_token"], PosthogJwtAudience.REPLAY_BLOCKS, verification_keys=["replay-blocks-key"]
            )
            assert {k: claims[k] for k in ("team_id", "session_id", "sub", "tier")} == {
                "team_id": self.team.pk,
                "session_id": session_id,
                "sub": viewer,
                "tier": "browser",
            }
            assert isinstance(claims["iat"], int)
            assert body["block_token_expires_at"] is not None
        else:
            assert urls == [None, None]
            assert body["block_token"] is None
        for flag_call in mock_feature_enabled.call_args_list:
            assert flag_call.kwargs["person_properties"] == {"cloud_deployment": "DEV", "team_id": self.team.pk}

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

    @parameterized.expand(
        [("enforced", True, status.HTTP_429_TOO_MANY_REQUESTS), ("log_only", False, status.HTTP_200_OK)]
    )
    @patch("posthog.session_recordings.session_recording_api.is_rate_limit_enabled", return_value=True)
    @patch("posthog.session_recordings.session_recording_api.recording_api_client")
    @patch("posthog.session_recordings.session_recording_api.list_blocks_async", new_callable=AsyncMock)
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_blob_v2_user_quota(
        self,
        _name,
        enforced,
        expected_status_over_quota,
        mock_get_session_recording,
        _mock_exists,
        mock_list_blocks,
        mock_recording_api_client,
        _mock_rate_limit_enabled,
    ):
        cache.clear()
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
        mock_storage.fetch_block = AsyncMock(return_value=b'{"timestamp": 1}')
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&start_blob_key=0&end_blob_key=0"

        with override_settings(SNAPSHOT_USER_RATE_BURST="2/minute", SNAPSHOT_USER_RATE_LIMIT_ENFORCED=enforced):
            assert self.client.get(url).status_code == status.HTTP_200_OK
            assert self.client.get(url).status_code == status.HTTP_200_OK
            assert self.client.get(url).status_code == expected_status_over_quota
        cache.clear()

    @patch(
        "posthog.session_recordings.session_recording_v2_service.fetch_blocks_from_recording_api",
        new_callable=AsyncMock,
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    def test_sources_listing_reports_a_deletion_despite_a_cached_listing(
        self,
        mock_get_session_recording,
        _mock_exists,
        mock_fetch_blocks,
    ):
        session_id = str(uuid7())
        recording = SessionRecording(session_id=session_id, team=self.team, deleted=False)
        mock_get_session_recording.return_value = recording
        cache.set(
            listing_cache_key(recording),
            [
                RecordingBlock(
                    key="key0",
                    start_byte=0,
                    end_byte=100,
                    start_timestamp="2024-01-01T00:00:00Z",
                    end_timestamp="2024-01-01T00:01:00Z",
                )
            ],
        )
        mock_fetch_blocks.side_effect = RecordingDeletedError("Recording has been deleted", deleted_at=1700000000)

        response = self.client.get(f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/")

        assert response.status_code == status.HTTP_410_GONE
        assert response.json()["error"] == "recording_deleted"
