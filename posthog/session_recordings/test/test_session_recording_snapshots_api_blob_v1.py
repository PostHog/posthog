from unittest.mock import call, patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
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

    @patch("posthog.session_recordings.session_recording_api.SessionRecording.get_or_build")
    @patch("posthog.session_recordings.session_recording_api.stream_from")
    def test_cannot_get_session_recording_blob_for_made_up_sessions(
        self, _mock_stream_from, mock_get_session_recording
    ) -> None:
        session_id = str(uuid7())
        blob_key = f"1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&blob_key={blob_key}"

        # by default a session recording is deleted, and _that_ is what we check for to see if it exists
        # so, we have to explicitly mark the mock as deleted
        mock_get_session_recording.return_value = SessionRecording(session_id=session_id, team=self.team, deleted=True)

        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_can_not_get_session_recording_blob_that_does_not_exist(self) -> None:
        session_id = str(uuid7())
        blob_key = f"session_recordings/team_id/{self.team.pk}/session_id/{session_id}/data/1682608337071"
        url = f"/api/projects/{self.team.pk}/session_recordings/{session_id}/snapshots/?source=blob_v2&blob_key={blob_key}"

        # TODO need to mock something else now i guess or this test is already somewhere else 🤞

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
            ("blob", status.HTTP_400_BAD_REQUEST),  # 404 because we didn't mock the right things for a 200
            ("realtime", status.HTTP_400_BAD_REQUEST),
            (None, status.HTTP_200_OK),  # No source parameter
            ("invalid_source", status.HTTP_400_BAD_REQUEST),
            ("", status.HTTP_400_BAD_REQUEST),
            ("BLOB", status.HTTP_400_BAD_REQUEST),  # Case-sensitive
            ("real-time", status.HTTP_400_BAD_REQUEST),
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
