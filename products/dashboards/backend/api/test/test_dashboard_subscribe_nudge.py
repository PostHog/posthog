from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.notifications.backend.facade.api import NotificationType, Priority, TargetType


@patch("products.dashboards.backend.api.dashboard.create_notification")
class TestDashboardSubscribeNudge(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Key metrics", created_by=self.user)

    def _post_nudge(self, dashboard_id: int) -> "object":
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

    def test_returns_404_for_other_team_dashboard(self, mock_create_notification: MagicMock) -> None:
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_dashboard = Dashboard.objects.create(team=other_team, name="Not yours")

        response = self._post_nudge(other_dashboard.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_create_notification.assert_not_called()

    def test_reports_not_created_when_notifications_unavailable(self, mock_create_notification: MagicMock) -> None:
        mock_create_notification.return_value = None

        response = self._post_nudge(self.dashboard.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"created": False}
