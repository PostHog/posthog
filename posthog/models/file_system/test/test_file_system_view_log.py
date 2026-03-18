from datetime import UTC, datetime
from typing import Protocol, cast

from freezegun import freeze_time

from django.test import TestCase

from posthog.models import Dashboard, FileSystem, FileSystemViewLog, Insight, Organization, Team, User
from posthog.models.file_system.file_system_view_log import get_recent_file_system_items, log_file_system_view


class FileSystemWithLastViewed(Protocol):
    ref: str
    last_viewed_at: datetime | None


class TestFileSystemViewLog(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user("user@posthog.com", "password", "User")

    def test_recent_items_sorting_by_views(self) -> None:
        insight = Insight.objects.create(
            team=self.team,
            name="Insight",
            saved=True,
            created_by=self.user,
            last_modified_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)

        with freeze_time("2024-01-01T10:00:00Z"):
            log_file_system_view(user=self.user, obj=insight)

        with freeze_time("2024-01-02T10:00:00Z"):
            log_file_system_view(user=self.user, obj=dashboard)

        with freeze_time("2024-01-03T10:00:00Z"):
            log_file_system_view(user=self.user, obj=dashboard)

        view_order = [
            cast(FileSystemWithLastViewed, item)
            for item in get_recent_file_system_items(team_id=self.team.id, user_id=self.user.id)
        ]

        self.assertGreaterEqual(len(view_order), 2)
        self.assertEqual([item.ref for item in view_order[:2]], [str(dashboard.id), insight.short_id])
        self.assertEqual(
            view_order[0].last_viewed_at,
            datetime(2024, 1, 3, 10, 0, 0, tzinfo=UTC),
        )

        dashboard_logs = FileSystemViewLog.objects.filter(
            team=self.team, user=self.user, type="dashboard", ref=str(dashboard.id)
        )
        self.assertEqual(dashboard_logs.count(), 1)
        self.assertEqual(
            dashboard_logs.first().viewed_at if dashboard_logs.first() else None,  # type: ignore
            datetime(2024, 1, 3, 10, 0, 0, tzinfo=UTC),
        )

        insight_logs = FileSystemViewLog.objects.filter(
            team=self.team, user=self.user, type="insight", ref=insight.short_id
        )
        self.assertEqual(insight_logs.count(), 1)
        insight_first_log = insight_logs.first()
        self.assertIsNotNone(insight_first_log)
        if insight_first_log is not None:
            self.assertEqual(
                insight_first_log.viewed_at,
                datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            )

        file_system_refs = FileSystem.objects.filter(team=self.team).values_list("type", "ref")
        self.assertIn(("insight", insight.short_id), file_system_refs)
        self.assertIn(("dashboard", str(dashboard.id)), file_system_refs)

    def test_log_updates_are_rate_limited(self) -> None:
        insight = Insight.objects.create(
            team=self.team,
            name="Insight",
            saved=True,
            created_by=self.user,
            last_modified_by=self.user,
        )

        with freeze_time("2024-02-01T10:00:00Z"):
            log_file_system_view(user=self.user, obj=insight)

        with freeze_time("2024-02-01T10:00:03Z"):
            log_file_system_view(user=self.user, obj=insight)

        with freeze_time("2024-02-01T10:00:10Z"):
            log_file_system_view(user=self.user, obj=insight)

        logs = FileSystemViewLog.objects.filter(team=self.team, user=self.user, type="insight", ref=insight.short_id)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(
            logs.first().viewed_at if logs.first() else None,  # type: ignore
            datetime(2024, 2, 1, 10, 0, 10, tzinfo=UTC),
        )
