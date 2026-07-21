from typing import TYPE_CHECKING

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework import status

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.dashboards.backend.models.dashboard import Dashboard
from products.notifications.backend.facade.api import NotificationType, Priority, TargetType

from ee.models.rbac.access_control import AccessControl


@patch("products.dashboards.backend.api.dashboard.create_notification")
class TestDashboardSubscribeNudge(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Key metrics", created_by=self.user)

    def _post_nudge(self, dashboard_id: int) -> "_MonkeyPatchedResponse":
        return self.client.post(f"/api/environments/{self.team.id}/dashboards/{dashboard_id}/subscribe_nudge/")

    def test_creates_notification_for_requesting_user(self, mock_create_notification: MagicMock) -> None:
        mock_create_notification.return_value = MagicMock()

        response = self._post_nudge(self.dashboard.id)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {"created": True}

        data = mock_create_notification.call_args.args[0]
        assert data.notification_type == NotificationType.SUBSCRIPTION_NUDGE
        assert data.priority == Priority.NORMAL
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.user.id)
        assert data.resource_type == "dashboard"
        assert data.resource_id == str(self.dashboard.id)
        assert data.title == "You keep coming back to Key metrics"
        assert data.source_url == f"/dashboard/{self.dashboard.id}/subscriptions/new?prefill=nudge&via=notification"

    def test_dedupes_repeat_calls_per_user_and_dashboard(self, mock_create_notification: MagicMock) -> None:
        mock_create_notification.return_value = MagicMock()

        first = self._post_nudge(self.dashboard.id)
        second = self._post_nudge(self.dashboard.id)

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.json() == {"created": False}
        assert mock_create_notification.call_count == 1

    @patch("products.dashboards.backend.api.dashboard.has_been_dispatched")
    def test_dedupes_from_the_notification_record_when_the_cache_is_lost(
        self, mock_has_been_dispatched: MagicMock, mock_create_notification: MagicMock
    ) -> None:
        mock_create_notification.return_value = MagicMock()
        mock_has_been_dispatched.return_value = False

        first = self._post_nudge(self.dashboard.id)
        assert first.status_code == status.HTTP_201_CREATED

        # The cache sentinel is gone (flush/eviction/Redis outage), but the notification record
        # is durable — the nudge stays once-ever rather than being re-delivered.
        cache.clear()
        mock_has_been_dispatched.return_value = True

        second = self._post_nudge(self.dashboard.id)

        assert second.status_code == status.HTTP_200_OK
        assert second.json() == {"created": False}
        assert mock_create_notification.call_count == 1
        mock_has_been_dispatched.assert_called_with(
            notification_type=NotificationType.SUBSCRIPTION_NUDGE,
            target_type=TargetType.USER,
            target_id=str(self.user.id),
            resource_id=str(self.dashboard.id),
        )

    def test_returns_404_for_other_team_dashboard(self, mock_create_notification: MagicMock) -> None:
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_dashboard = Dashboard.objects.create(team=other_team, name="Not yours")

        response = self._post_nudge(other_dashboard.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_create_notification.assert_not_called()

    def test_releases_the_dedupe_sentinel_when_notifications_unavailable(
        self, mock_create_notification: MagicMock
    ) -> None:
        mock_create_notification.return_value = None

        response = self._post_nudge(self.dashboard.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"created": False}

        # The sentinel must not burn the nudge for 30 days: once notifications become
        # available again, the next call creates.
        mock_create_notification.return_value = MagicMock()
        retry = self._post_nudge(self.dashboard.id)
        assert retry.status_code == status.HTTP_201_CREATED
        assert retry.json() == {"created": True}

    def test_releases_the_dedupe_sentinel_when_create_notification_raises(
        self, mock_create_notification: MagicMock
    ) -> None:
        mock_create_notification.side_effect = RuntimeError("notifications backend down")

        response = self._post_nudge(self.dashboard.id)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        # The sentinel must be released on failure, not left to burn the nudge for 30 days:
        # once the backend recovers, the next call creates.
        mock_create_notification.side_effect = None
        mock_create_notification.return_value = MagicMock()
        retry = self._post_nudge(self.dashboard.id)
        assert retry.status_code == status.HTTP_201_CREATED
        assert retry.json() == {"created": True}

    def test_rejects_viewer_only_access_control(self, mock_create_notification: MagicMock) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        viewer = self._create_user("viewer@posthog.com", level=OrganizationMembership.Level.MEMBER)
        AccessControl.objects.create(
            resource="dashboard", resource_id=str(self.dashboard.id), team=self.team, access_level="viewer"
        )

        self.client.force_login(viewer)
        response = self._post_nudge(self.dashboard.id)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_create_notification.assert_not_called()

    def test_rejects_read_scoped_api_key(self, mock_create_notification: MagicMock) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="dashboard read only",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=["dashboard:read"],
            scoped_teams=[],
            scoped_organizations=[],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/subscribe_nudge/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_create_notification.assert_not_called()
