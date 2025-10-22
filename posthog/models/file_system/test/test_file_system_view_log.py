from datetime import UTC, datetime
from typing import Protocol, cast

from freezegun import freeze_time

from django.test import TestCase

from posthog.models import Dashboard, FileSystem, FileSystemViewLog, Insight, Organization, Team, User
from posthog.models.file_system.file_system_view_log import (
    RecentViewer,
    get_recent_file_system_items,
    get_recent_viewers_for_resource,
    log_file_system_view,
)


class FileSystemWithViewStats(Protocol):
    ref: str
    view_count: int
    last_viewed_at: datetime | None


class TestFileSystemViewLog(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user("user@posthog.com", "password", "User")

    def test_recent_items_sorting_by_views(self) -> None:
        insight = Insight.objects.create(
            team=self.team, name="Insight", created_by=self.user, last_modified_by=self.user
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)

        with freeze_time("2024-01-01T10:00:00Z"):
            log_file_system_view(user=self.user, obj=insight)

        with freeze_time("2024-01-02T10:00:00Z"):
            log_file_system_view(user=self.user, obj=dashboard)

        with freeze_time("2024-01-03T10:00:00Z"):
            log_file_system_view(user=self.user, obj=dashboard)

        view_order = [
            cast(FileSystemWithViewStats, item)
            for item in get_recent_file_system_items(team_id=self.team.id, user_id=self.user.id)
        ]

        self.assertGreaterEqual(len(view_order), 2)
        self.assertEqual([item.ref for item in view_order[:2]], [str(dashboard.id), insight.short_id])
        self.assertEqual([item.view_count for item in view_order[:2]], [2, 1])
        self.assertEqual(
            view_order[0].last_viewed_at,
            datetime(2024, 1, 3, 10, 0, 0, tzinfo=UTC),
        )

        dashboard_logs = FileSystemViewLog.objects.filter(
            team=self.team, user=self.user, type="dashboard", ref=str(dashboard.id)
        )
        self.assertEqual(dashboard_logs.count(), 2)

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

    def test_recent_viewers_for_resource(self) -> None:
        other_user = User.objects.create_user("other@posthog.com", "password", "Other")
        insight = Insight.objects.create(
            team=self.team, name="Insight", created_by=self.user, last_modified_by=self.user
        )

        with freeze_time("2024-01-01T09:00:00Z"):
            log_file_system_view(user=self.user, obj=insight)

        with freeze_time("2024-01-01T10:00:00Z"):
            log_file_system_view(user=other_user, obj=insight)

        with freeze_time("2024-01-01T11:00:00Z"):
            log_file_system_view(user=self.user, obj=insight)

        viewers = get_recent_viewers_for_resource(team_id=self.team.id, file_type="insight", ref=insight.short_id)
        self.assertEqual(
            viewers,
            [
                RecentViewer(user_id=self.user.id, last_viewed_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)),
                RecentViewer(user_id=other_user.id, last_viewed_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)),
            ],
        )

        recent_only = get_recent_viewers_for_resource(
            team_id=self.team.id,
            file_type="insight",
            ref=insight.short_id,
            since=datetime(2024, 1, 1, 10, 30, 0, tzinfo=UTC),
        )
        self.assertEqual(
            recent_only,
            [RecentViewer(user_id=self.user.id, last_viewed_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC))],
        )

        limited = get_recent_viewers_for_resource(
            team_id=self.team.id, file_type="insight", ref=insight.short_id, limit=1
        )
        self.assertEqual(
            limited,
            [RecentViewer(user_id=self.user.id, last_viewed_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC))],
        )
