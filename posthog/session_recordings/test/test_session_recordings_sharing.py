import uuid
from unittest.mock import MagicMock, patch

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_team import create_team
from posthog.clickhouse.client import sync_execute
from posthog.models import Person, SessionRecording
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)
from posthog.session_recordings.queries_to_replace.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
)


class TestSessionRecordingsSharing(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
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

    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_enable_sharing_creates_access_token(self, mock_copy_objects: MagicMock) -> None:
        """Test that enabling sharing on a recording creates an access token"""
        mock_copy_objects.return_value = 2

        session_id = str(uuid.uuid4())
        with freeze_time("2023-01-01T12:00:00Z"):
            self.produce_replay_summary(
                "user",
                session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
            )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "access_token" in response.json()
        assert len(response.json()["access_token"]) > 0

    @parameterized.expand(
        [
            # Test accessing a different session ID than the one shared
            (
                "different_session_id",
                lambda self, token: f"/api/projects/{self.team.id}/session_recordings/2?sharing_access_token={token}",
                status.HTTP_403_FORBIDDEN,
            ),
            # Test accessing the list endpoint (not allowed with sharing token)
            (
                "list_endpoint",
                lambda self, token: f"/api/projects/{self.team.id}/session_recordings?sharing_access_token={token}",
                status.HTTP_403_FORBIDDEN,
            ),
            # Test accessing with a non-existent team ID
            (
                "non_existent_team",
                lambda self, token: f"/api/projects/12345/session_recordings?sharing_access_token={token}",
                status.HTTP_403_FORBIDDEN,
            ),
            # Test accessing the same session from a different team
            (
                "different_team_same_session",
                lambda self,
                token: f"/api/projects/{self.other_team.id}/session_recordings/{self.session_id}?sharing_access_token={token}",
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_sharing_token_forbidden_access_scenarios(
        self, _name: str, url_builder, expected_status: int, mock_copy_objects: MagicMock
    ) -> None:
        """Test various forbidden access scenarios with sharing tokens"""
        mock_copy_objects.return_value = 2

        # Setup
        self.other_team = create_team(organization=self.organization)
        self.session_id = str(uuid.uuid4())

        with freeze_time("2023-01-01T12:00:00Z"):
            self.produce_replay_summary(
                "user",
                self.session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
            )

        # Enable sharing and get token
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}/sharing",
            {"enabled": True},
        )
        token = patch_response.json()["access_token"]

        # Logout to test unauthenticated access
        self.client.logout()

        # Test the forbidden scenario
        url = url_builder(self, token)
        response = self.client.get(url)
        assert response.status_code == expected_status

    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_sharing_token_allows_authorized_access(self, mock_copy_objects: MagicMock) -> None:
        """Test that a valid sharing token allows access to the shared recording"""
        mock_copy_objects.return_value = 2

        session_id = str(uuid.uuid4())
        with freeze_time("2023-01-01T12:00:00Z"):
            self.produce_replay_summary(
                "user",
                session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
            )

        # Enable sharing and get token
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/sharing",
            {"enabled": True},
        )
        token = patch_response.json()["access_token"]

        # Logout and test access
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}?sharing_access_token={token}"
        )
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == {
            "id": session_id,
            "recording_duration": 0,
            "start_time": "2022-12-31T12:00:00Z",
            "end_time": "2022-12-31T12:00:00Z",
        }

    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_sharing_token_allows_snapshot_access_within_ttl(self, mock_copy_objects: MagicMock) -> None:
        """Test that sharing token allows access to snapshots within TTL"""
        mock_copy_objects.return_value = 2

        session_id = str(uuid.uuid4())

        # Create initial recording
        with freeze_time("2023-01-01T12:00:00Z"):
            self.produce_replay_summary(
                "user",
                session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
            )

        # Enable sharing
        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/sharing",
            {"enabled": True},
        )
        token = patch_response.json()["access_token"]

        # Create a snapshot within TTL
        self.produce_replay_summary(
            "user",
            session_id,
            # a little before now, since the DB checks if the snapshot is within TTL and before now
            # if the test runs too quickly it looks like the snapshot is not there
            now() - relativedelta(seconds=1),
            team_id=self.team.pk,
        )

        # Logout and test snapshot access
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?sharing_access_token={token}"
        )
        assert response.status_code == status.HTTP_200_OK
