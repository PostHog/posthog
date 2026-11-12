from collections.abc import AsyncIterator
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.http import StreamingHttpResponse
from django.test import override_settings

import aiohttp
from asgiref.sync import async_to_sync
from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, SessionRecording, SharingConfiguration, User
from posthog.models.utils import generate_random_token_personal, hash_key_value, uuid7
from posthog.session_recordings.recordings.errors import RecordingDeletedError
from posthog.session_recordings.recordings.raw_snapshot_stream import RAW_SNAPSHOT_STREAM_BATCH_SIZE
from posthog.session_recordings.session_recording_v2_service import RecordingBlock


def _block(index: int = 0) -> RecordingBlock:
    return RecordingBlock(
        key=f"key{index}",
        start_byte=0,
        end_byte=100,
        start_timestamp="2026-01-01T00:00:00Z",
        end_timestamp="2026-01-01T00:01:00Z",
    )


class TestSessionRecordingRawSnapshotsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.session_id = str(uuid7())
        self.url = f"/api/projects/{self.team.pk}/session_recordings/{self.session_id}/raw_snapshots/"
        self._set_file_export(True)

        self.flag = self._start_patch(
            "posthog.session_recordings.recordings.raw_snapshot_stream.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.list_blocks = self._start_patch(
            "posthog.session_recordings.session_recording_api.fetch_blocks_from_recording_api",
            new_callable=AsyncMock,
            return_value=[_block()],
        )
        self.storage = MagicMock()
        self.storage.fetch_block = AsyncMock(return_value=b'["window",{"type":4}]')
        recording_api_client = self._start_patch(
            "posthog.session_recordings.recordings.raw_snapshot_stream.recording_api_client"
        )
        recording_api_client.return_value.__aenter__.return_value = self.storage

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _start_patch(self, target: str, **kwargs) -> MagicMock:
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _set_file_export(self, available: bool) -> None:
        self.organization.available_product_features = (
            [{"key": AvailableFeature.RECORDINGS_FILE_EXPORT, "name": "Recordings file export"}] if available else []
        )
        self.organization.save()

    def _personal_api_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test key",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_teams=[self.team.pk],
        )
        return value

    @parameterized.expand(
        [
            ("session", status.HTTP_200_OK),
            ("session_asking_for_jsonl", status.HTTP_200_OK),
            ("personal_api_key_with_replay_read", status.HTTP_200_OK),
            ("personal_api_key_without_replay_read", status.HTTP_403_FORBIDDEN),
            ("share_link", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_who_can_stream_a_recording(self, auth: str, expected_status: int) -> None:
        url = self.url
        headers = {}
        if auth == "session_asking_for_jsonl":
            headers = {"accept": "application/jsonl"}
        if auth == "share_link":
            recording = SessionRecording.objects.create(session_id=self.session_id, team=self.team)
            sharing = SharingConfiguration.objects.create(team=self.team, recording=recording, enabled=True)
            url = f"{url}?sharing_access_token={sharing.access_token}"
        if auth == "personal_api_key_with_replay_read":
            headers = {"authorization": f"Bearer {self._personal_api_key(['session_recording:read'])}"}
        if auth == "personal_api_key_without_replay_read":
            headers = {"authorization": f"Bearer {self._personal_api_key(['insight:read'])}"}
        if not auth.startswith("session"):
            self.client.logout()

        response = self.client.get(url, headers=headers)

        assert response.status_code == expected_status
        if expected_status == status.HTTP_200_OK:
            assert response.headers["content-type"] == "application/jsonl"
            assert b"".join(response) == b'["window",{"type":4}]\n'

    def test_project_without_the_flag_cannot_stream(self) -> None:
        self.flag.return_value = False

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.storage.fetch_block.assert_not_awaited()

    def test_plan_without_file_export_cannot_stream(self) -> None:
        self._set_file_export(False)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED

    def test_deleted_recording_returns_410_before_the_stream_starts(self) -> None:
        self.storage.fetch_block.side_effect = RecordingDeletedError("recording deleted", deleted_at=1700000000)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_410_GONE
        assert response.json()["error"] == "recording_deleted"

    @parameterized.expand(
        [
            ("recording_has_no_blocks", {"return_value": []}, status.HTTP_404_NOT_FOUND),
            (
                "storage_listing_fails",
                {"side_effect": aiohttp.ClientError("recording-api is down")},
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        ]
    )
    def test_listing_outcome_decides_the_status(self, _name: str, listing: dict, expected_status: int) -> None:
        self.list_blocks.configure_mock(**listing)

        response = self.client.get(self.url)

        assert response.status_code == expected_status

    def test_later_batches_are_read_only_as_the_client_consumes_the_stream(self) -> None:
        self.list_blocks.return_value = [_block(i) for i in range(RAW_SNAPSHOT_STREAM_BATCH_SIZE * 2)]
        self.async_client.force_login(self.user)

        async def read() -> tuple[int, int]:
            response = await self.async_client.get(self.url)
            chunks = cast(AsyncIterator[bytes], cast(StreamingHttpResponse, response).streaming_content)
            body = await anext(chunks)
            fetched_after_the_first_chunk = self.storage.fetch_block.await_count
            async for chunk in chunks:
                body += chunk
            return fetched_after_the_first_chunk, body.count(b"\n")

        fetched_after_the_first_chunk, lines = async_to_sync(read)()

        assert fetched_after_the_first_chunk == RAW_SNAPSHOT_STREAM_BATCH_SIZE
        assert lines == RAW_SNAPSHOT_STREAM_BATCH_SIZE * 2

    @override_settings(RAW_SNAPSHOT_STREAM_RATE_PAID_BURST="1/minute")
    @patch("posthog.session_recordings.session_recording_api.get_cached_org_tier", return_value="paid")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_each_logged_in_caller_has_its_own_rate_limit(
        self, _mock_rate_limit_enabled: MagicMock, _mock_tier: MagicMock
    ) -> None:
        assert self.client.get(self.url).status_code == status.HTTP_200_OK
        assert self.client.get(self.url).status_code == status.HTTP_429_TOO_MANY_REQUESTS

        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        self.client.force_login(other_user)

        assert self.client.get(self.url).status_code == status.HTTP_200_OK
