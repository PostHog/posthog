from datetime import timedelta
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.models import SessionRecording, SharingConfiguration, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight


class TestBackfillSharingPublishers(BaseTest):
    @parameterized.expand(
        [
            ("dashboard", "Dashboard"),
            ("insight", "Insight"),
            ("notebook", "Notebook"),
            ("recording", "SessionRecording"),
        ]
    )
    def test_latest_publisher_is_backfilled_without_overwriting_known_attribution(self, kind: str, scope: str) -> None:
        resource = {
            "dashboard": lambda: Dashboard.objects.create(team=self.team),
            "insight": lambda: Insight.objects.create(team=self.team),
            "notebook": lambda: Notebook.objects.create(team=self.team, title="Test notebook"),
            "recording": lambda: SessionRecording.objects.create(team=self.team, session_id="test-recording"),
        }[kind]()
        identifier = (
            resource.short_id if kind == "notebook" else resource.session_id if kind == "recording" else resource.pk
        )
        share = SharingConfiguration.objects.create(team=self.team, **{kind: resource}, enabled=True)
        known = SharingConfiguration.objects.create(team=self.team, **{kind: resource}, shared_by=self.user)
        latest = User.objects.create_and_join(self.organization, "latest@example.com", None)
        for user, date in ((self.user, timezone.now() - timedelta(days=1)), (latest, timezone.now())):
            ActivityLog.objects.create(
                team_id=self.team.pk,
                scope=scope,
                activity="sharing enabled",
                item_id=str(identifier),
                user=user,
                created_at=date,
                detail={"changes": [{"field": "sharing", "before": False, "after": True}]},
            )
        other_team = Team.objects.create(organization=self.organization)
        ActivityLog.objects.create(
            team_id=other_team.pk, scope=scope, activity="sharing enabled", item_id=str(identifier), user=self.user
        )
        call_command("backfill_sharing_publishers", dry_run=True, batch_size=1, stdout=StringIO())
        share.refresh_from_db()
        assert share.shared_by_id is None
        call_command("backfill_sharing_publishers", team_id=other_team.pk, stdout=StringIO())
        share.refresh_from_db()
        assert share.shared_by_id is None
        for _ in range(2):
            call_command("backfill_sharing_publishers", batch_size=1, stdout=StringIO())
        share.refresh_from_db()
        known.refresh_from_db()
        assert share.shared_by_id == latest.id
        assert known.shared_by_id == self.user.id

    def test_missing_history_and_deleted_latest_publisher_remain_unknown(self) -> None:
        for deleted_publisher in (False, True):
            dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
            share = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
            if deleted_publisher:
                ActivityLog.objects.create(
                    team_id=self.team.pk,
                    scope="Dashboard",
                    activity="sharing enabled",
                    item_id=str(dashboard.pk),
                    user=self.user,
                    created_at=timezone.now() - timedelta(days=1),
                )
                ActivityLog.objects.create(
                    team_id=self.team.pk,
                    scope="Dashboard",
                    activity="sharing enabled",
                    item_id=str(dashboard.pk),
                    user=None,
                )
            call_command("backfill_sharing_publishers", stdout=StringIO())
            share.refresh_from_db()
            assert share.shared_by_id is None

    @parameterized.expand([("insight", "Insight"), ("notebook", "Notebook")])
    def test_ambiguous_settings_history_does_not_attribute_the_editor(self, kind: str, scope: str) -> None:
        resource = (Insight if kind == "insight" else Notebook).objects.create(team=self.team)
        share = SharingConfiguration.objects.create(team=self.team, **{kind: resource}, enabled=True)
        ActivityLog.objects.create(
            team_id=self.team.pk,
            scope=scope,
            activity="sharing enabled",
            item_id=str(resource.pk if kind == "insight" else resource.short_id),
            user=self.user,
            detail={"changes": [{"field": "sharing", "after": True}]},
        )
        call_command("backfill_sharing_publishers", stdout=StringIO())
        share.refresh_from_db()
        assert share.shared_by_id is None
