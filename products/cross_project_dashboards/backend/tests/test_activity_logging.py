from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cross_project_dashboards.backend.models import CrossProjectDashboard


class TestCrossProjectDashboardActivityLogging(BaseTest):
    def test_creating_a_dashboard_logs_against_the_organization(self):
        CrossProjectDashboard.objects.create(
            organization=self.organization, name="Company overview", created_by=self.user
        )
        log = ActivityLog.objects.filter(scope="CrossProjectDashboard").latest("created_at")
        assert log.organization_id == self.organization.id
        # ActivityLog requires a team id or an organization id, not both. An org dashboard has
        # no team, so the organization carries the row.
        assert log.team_id is None
        assert log.activity == "created"
        assert (log.detail or {})["name"] == "Company overview"

    def test_renaming_a_dashboard_logs_the_change(self):
        dashboard = CrossProjectDashboard.objects.create(
            organization=self.organization, name="Before", created_by=self.user
        )
        dashboard.name = "After"
        dashboard.save()
        log = ActivityLog.objects.filter(scope="CrossProjectDashboard", activity="updated").latest("created_at")
        assert log.organization_id == self.organization.id
        assert log.team_id is None
