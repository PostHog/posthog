from datetime import datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard


@time_machine.travel("2026-11-09T12:00:00Z", tick=False)
class TestDashboardActivitySummary(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Key metrics", created_by=self.user)
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", None, "Other")

    def _get_summary(self) -> dict:
        response = self.client.get(f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/activity_summary/")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _log_activity(
        self, *, days_ago: int, client: str | None = None, is_system: bool = False, was_impersonated: bool = False
    ) -> None:
        log = ActivityLog.objects.create(
            team_id=self.team.id,
            scope="Dashboard",
            item_id=str(self.dashboard.id),
            activity="updated",
            user=self.other_user,
            client=client,
            is_system=is_system,
            was_impersonated=was_impersonated,
        )
        ActivityLog.objects.filter(id=log.id).update(created_at=timezone.now() - timedelta(days=days_ago))

    def _log_view(self, user: User, *, days_ago: int) -> None:
        FileSystemViewLog.objects.create(
            team=self.team,
            user=user,
            type="dashboard",
            ref=str(self.dashboard.id),
            viewed_at=timezone.now() - timedelta(days=days_ago),
        )

    def test_empty_summary(self) -> None:
        assert self._get_summary() == {
            "last_edited_at": None,
            "last_edited_by": None,
            "last_edited_client": None,
            "last_viewed_by_others_at": None,
            "last_viewed_by_others_user": None,
            "recent_viewer_count": 0,
        }

    def test_last_edit_ignores_system_and_impersonated_changes(self) -> None:
        self._log_activity(days_ago=90, client="mcp")
        self._log_activity(days_ago=1, is_system=True)
        self._log_activity(days_ago=2, was_impersonated=True)

        summary = self._get_summary()

        assert datetime.fromisoformat(summary["last_edited_at"]) == timezone.now() - timedelta(days=90)
        assert summary["last_edited_by"]["id"] == self.other_user.id
        assert summary["last_edited_client"] == "mcp"

    def test_views_exclude_requesting_user_from_last_view_but_count_recent_viewers(self) -> None:
        self._log_view(self.user, days_ago=0)
        self._log_view(self.other_user, days_ago=45)

        summary = self._get_summary()

        assert datetime.fromisoformat(summary["last_viewed_by_others_at"]) == timezone.now() - timedelta(days=45)
        assert summary["last_viewed_by_others_user"]["id"] == self.other_user.id
        assert summary["recent_viewer_count"] == 1

    def test_other_dashboards_views_are_not_counted(self) -> None:
        other_dashboard = Dashboard.objects.create(team=self.team, name="Other")
        FileSystemViewLog.objects.create(
            team=self.team, user=self.other_user, type="dashboard", ref=str(other_dashboard.id)
        )

        assert self._get_summary()["last_viewed_by_others_at"] is None
