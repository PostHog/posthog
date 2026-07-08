import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_team import create_team
from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import SessionRecording
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class TestSessionRecordingsSharing(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()

        with freeze_time("2023-01-01T12:00:00Z"):
            self.session_id = str(uuid7())
            self.produce_replay_summary(
                "user",
                self.session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
            )

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

    def _enable_sharing(self, session_id: str) -> str | None:
        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/sharing",
            {"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "access_token" in response.json()
        return response.json()["access_token"]

    @freeze_time("2023-01-01T12:00:00Z")
    def test_enable_sharing_creates_access_token(self) -> None:
        token = self._enable_sharing(self.session_id)
        assert isinstance(token, str) and len(token) > 0

    @parameterized.expand(
        [
            (
                "accessing a different session ID than the one shared",
                lambda self, token: f"/api/projects/{self.team.id}/session_recordings/2?sharing_access_token={token}",
            ),
            (
                "accessing the list endpoint (not allowed with sharing token)",
                lambda self, token: f"/api/projects/{self.team.id}/session_recordings?sharing_access_token={token}",
            ),
            (
                "accessing with a non-existent team ID",
                lambda self, token: f"/api/projects/12345/session_recordings?sharing_access_token={token}",
            ),
            (
                "accessing the same session from a different team",
                lambda self, token: (
                    f"/api/projects/{self.other_team.id}/session_recordings/{self.session_id}?sharing_access_token={token}"
                ),
            ),
        ]
    )
    @freeze_time("2023-01-01T12:00:00Z")
    def test_sharing_token_forbidden_access_scenarios(self, _name: str, url_builder) -> None:
        self.other_team = create_team(organization=self.organization)

        token = self._enable_sharing(self.session_id)

        self.client.logout()

        url = url_builder(self, token)
        response = self.client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @freeze_time("2023-01-01T12:00:00Z")
    def test_sharing_token_allows_authorized_access(self) -> None:
        token = self._enable_sharing(self.session_id)

        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}?sharing_access_token={token}"
        )
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == {
            "id": self.session_id,
            "recording_duration": 0,
            "start_time": "2022-12-31T12:00:00Z",
            "end_time": "2022-12-31T12:00:00Z",
        }

    @freeze_time("2023-01-01T12:00:00Z")
    def test_sharing_token_allows_snapshot_access(self) -> None:
        token = self._enable_sharing(self.session_id)

        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}/snapshots?sharing_access_token={token}"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()


@pytest.mark.ee
class TestSessionRecordingsSharingAccessControl(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecording.objects.all().delete()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.member_user = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")

        with freeze_time("2023-01-01T12:00:00Z"):
            self.session_id = str(uuid7())
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=self.session_id,
                distinct_id="user",
                first_timestamp=now() - relativedelta(days=1),
                last_timestamp=now() - relativedelta(days=1),
                ensure_analytics_event_in_session=False,
            )

    def _grant_recording_access(self, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=self.member_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    @parameterized.expand(
        [
            ("viewer", status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_200_OK),
        ]
    )
    @freeze_time("2023-01-01T12:00:00Z")
    def test_enable_sharing_requires_editor_access(self, access_level: str, expected_status: int) -> None:
        self._grant_recording_access(access_level)
        self.client.force_login(self.member_user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{self.session_id}/sharing",
            {"enabled": True},
        )

        assert response.status_code == expected_status, response.json()
