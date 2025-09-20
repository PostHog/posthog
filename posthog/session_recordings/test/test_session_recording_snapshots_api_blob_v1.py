import re
import json
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import MagicMock, call, patch

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, PersonalAPIKey, SessionRecording
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.test import setup_stream_from


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
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_get_snapshots_v2_default_response(self, mock_list_objects: MagicMock, _mock_exists: MagicMock) -> None:
        session_id = str(uuid7())
        timestamp = round(now().timestamp() * 1000)
        mock_list_objects.return_value = [
            f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{timestamp - 10000}-{timestamp - 5000}",
            f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{timestamp - 5000}-{timestamp}",
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots")
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob",
                    "start_timestamp": "2022-12-31T23:59:50Z",
                    "end_timestamp": "2022-12-31T23:59:55Z",
                    "blob_key": "1672531190000-1672531195000",
                },
                {
                    "source": "blob",
                    "start_timestamp": "2022-12-31T23:59:55Z",
                    "end_timestamp": "2023-01-01T00:00:00Z",
                    "blob_key": "1672531195000-1672531200000",
                },
                {
                    "source": "realtime",
                    "start_timestamp": "2022-12-31T23:59:55Z",
                    "end_timestamp": None,
                    "blob_key": None,
                },
            ]
        }
        mock_list_objects.assert_called_with(f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data")

    @freeze_time("2023-01-01T00:00:00Z")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_list_snapshot_sources_blobby_v1_from_lts(
        self, mock_list_objects: MagicMock, _mock_exists: MagicMock
    ) -> None:
        session_id = str(uuid7())
        timestamp = round(now().timestamp() * 1000)

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            storage_version="2023-08-01",
            object_storage_path="an lts stored object path",
        )

        def list_objects_func(path: str) -> list[str]:
            # this mock simulates a recording whose blob storage has been deleted by TTL
            # but which has been stored in LTS blob storage
            if path == "an lts stored object path":
                return [
                    f"an lts stored object path/{timestamp - 10000}-{timestamp - 5000}",
                    f"an lts stored object path/{timestamp - 5000}-{timestamp}",
                ]
            else:
                return []

        mock_list_objects.side_effect = list_objects_func

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?")
        assert response.status_code == 200
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob",
                    "start_timestamp": "2022-12-31T23:59:50Z",
                    "end_timestamp": "2022-12-31T23:59:55Z",
                    "blob_key": "1672531190000-1672531195000",
                },
                {
                    "source": "blob",
                    "start_timestamp": "2022-12-31T23:59:55Z",
                    "end_timestamp": "2023-01-01T00:00:00Z",
                    "blob_key": "1672531195000-1672531200000",
                },
            ]
        }
        assert mock_list_objects.call_args_list == [
            call("an lts stored object path"),
        ]

    @freeze_time("2023-01-01T00:00:00Z")
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_get_snapshots_v2_default_response_no_realtime_if_old(self, mock_list_objects, _mock_exists) -> None:
        session_id = str(uuid7())
        old_timestamp = round((now() - timedelta(hours=26)).timestamp() * 1000)

        mock_list_objects.return_value = [
            f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{old_timestamp - 10000}-{old_timestamp}",
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?")
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob",
                    "start_timestamp": "2022-12-30T21:59:50Z",
                    "end_timestamp": "2022-12-30T22:00:00Z",
                    "blob_key": "1672437590000-1672437600000",
                }
            ]
        }

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.stream_from", return_value=setup_stream_from())
    def test_can_get_session_recording_blob(
        self,
        _mock_stream_from,
        mock_presigned_url,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        blob_key = f"1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob&blob_key={blob_key}"

        # by default a session recording is deleted, so we have to explicitly mark the mock as not deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        def presigned_url_sideeffect(key: str, **kwargs):
            if key == f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{blob_key}":
                return f"https://test.com/"
            else:
                return None

        mock_presigned_url.side_effect = presigned_url_sideeffect

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        # default headers if the object store does nothing
        headers = response.headers.__dict__["_store"]
        server_timing_headers = headers.pop("server-timing")[1]
        assert re.match(r"get_recording;dur=\d+\.\d+, stream_blob_to_client;dur=\d+\.\d+", server_timing_headers)
        assert headers == {
            "content-type": ("Content-Type", "application/json"),
            "cache-control": ("Cache-Control", "max-age=3600"),
            "content-disposition": ("Content-Disposition", "inline"),
            "allow": ("Allow", "GET, HEAD, OPTIONS"),
            "x-frame-options": ("X-Frame-Options", "SAMEORIGIN"),
            "content-length": ("Content-Length", "15"),
            "vary": ("Vary", "Origin"),
            "x-content-type-options": ("X-Content-Type-Options", "nosniff"),
            "referrer-policy": ("Referrer-Policy", "same-origin"),
            "cross-origin-opener-policy": ("Cross-Origin-Opener-Policy", "same-origin"),
        }

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch(
        "posthog.session_recordings.session_recording_api.stream_from",
        return_value=setup_stream_from(
            {
                "Content-Type": "application/magical",
                "Content-Encoding": "from the mock",
                "ETag": 'W/"represents the file contents"',
                "Cache-Control": "more specific cache control",
            }
        ),
    )
    def test_can_override_headers_from_object_storage(
        self,
        _mock_stream_from,
        mock_presigned_url,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        blob_key = f"1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob&blob_key={blob_key}"

        # by default a session recording is deleted, so we have to explicitly mark the mock as not deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        def presigned_url_sideeffect(key: str, **kwargs):
            if key == f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{blob_key}":
                return f"https://test.com/"
            else:
                return None

        mock_presigned_url.side_effect = presigned_url_sideeffect

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        assert response.headers.get("content-type") == "application/json"  # we don't override this
        assert response.headers.get("content-encoding") is None  # we don't override this
        assert response.headers.get("etag") == "represents the file contents"  # we don't allow weak etags
        assert response.headers.get("cache-control") == "more specific cache control"

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.stream_from")
    def test_validates_blob_keys(
        self,
        mock_stream_from,
        mock_presigned_url,
        mock_get_session_recording,
        mock_exists,
    ) -> None:
        session_id = str(uuid7())
        blob_key = f"../try/to/escape/into/other/directories"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob&blob_key={blob_key}"

        # by default a session recording is deleted, so we have to explicitly mark the mock as not deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        def presigned_url_sideeffect(key: str, **kwargs):
            if key == f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/{blob_key}":
                return f"https://test.com/"
            else:
                return None

        mock_presigned_url.side_effect = presigned_url_sideeffect

        response = self.client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # we don't generate a pre-signed url if the blob key is invalid
        assert mock_presigned_url.call_count == 0
        # we don't try to load the data if the blob key is invalid
        assert mock_stream_from.call_count == 0
        # we do check the session before validating input
        # TODO it would be maybe cheaper to validate the input first
        assert mock_get_session_recording.call_count == 1
        assert mock_exists.call_count == 1

    @parameterized.expand([("2024-04-30"), (None)])
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.get_realtime_snapshots")
    @patch("posthog.session_recordings.session_recording_api.stream_from")
    def test_can_get_session_recording_realtime(
        self,
        version_param,
        _mock_stream_from,
        mock_realtime_snapshots,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        """
        includes regression test to allow utf16 surrogate pairs in realtime snapshots response
        """

        expected_response = b'{"some": "\\ud801\\udc37 probably from console logs"}\n{"some": "more data"}'

        version_param = f"&version={version_param}" if version_param else ""
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=realtime{version_param}"

        # by default a session recording is deleted, so we have to explicitly mark the mock as not deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        mock_realtime_snapshots.return_value = [
            json.dumps({"some": "\ud801\udc37 probably from console logs"}),
            json.dumps({"some": "more data"}),
        ]

        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.headers.get("content-type") == "application/json"
        assert response.content == expected_response

    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.stream_from")
    def test_cannot_get_session_recording_blob_for_made_up_sessions(
        self, _mock_stream_from, _mock_presigned_url, mock_get_session_recording
    ) -> None:
        session_id = str(uuid7())
        blob_key = f"1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob&blob_key={blob_key}"

        # by default a session recording is deleted, and _that_ is what we check for to see if it exists
        # so, we have to explicitly mark the mock as deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=True)

        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    def test_can_not_get_session_recording_blob_that_does_not_exist(self, mock_presigned_url) -> None:
        session_id = str(uuid7())
        blob_key = f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob&blob_key={blob_key}"

        mock_presigned_url.return_value = None

        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # checks that we 404 without patching the "exists" check
    # that is patched in other tests or freezing time doesn't work
    def test_404_when_no_snapshots(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/1/snapshots?",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthoganalytics.capture")
    def test_snapshots_api_called_with_personal_api_key(self, mock_capture):
        session_id = str(uuid7())
        self.produce_replay_summary("user", session_id, now() - relativedelta(days=1))

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scopes=["session_recording:read"],
            scoped_teams=[self.team.pk],
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots",
            HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        assert mock_capture.call_args_list[0] == call(
            event="snapshots_api_called_with_personal_api_key",
            distinct_id=self.user.distinct_id,
            properties={
                "key_label": "X",
                "key_scopes": ["session_recording:read"],
                "key_scoped_teams": [self.team.pk],
                "session_requested": session_id,
                # none because it's all mock data
                "recording_start_time": None,
                "source": "listing",
            },
        )

    @parameterized.expand(
        [
            ("blob", True, status.HTTP_404_NOT_FOUND),  # 404 because we didn't mock the right things for a 200
            ("realtime", True, status.HTTP_200_OK),
            (None, True, status.HTTP_200_OK),  # No source parameter
            ("invalid_source", False, status.HTTP_400_BAD_REQUEST),
            ("", False, status.HTTP_400_BAD_REQUEST),
            ("BLOB", False, status.HTTP_400_BAD_REQUEST),  # Case-sensitive
            ("real-time", False, status.HTTP_400_BAD_REQUEST),
        ]
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    @patch("posthog.session_recordings.session_recording_api.get_realtime_snapshots")
    def test_snapshots_source_parameter_validation(
        self,
        source,
        should_work,
        expected_status,
        mock_realtime_snapshots,
        mock_list_objects,
        mock_presigned_url,
        mock_get_session_recording,
        _mock_exists,
    ) -> None:
        session_id = str(uuid7())
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=False)

        # Basic mocking for successful cases
        mock_realtime_snapshots.return_value = []
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
