from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cross_project_dashboards.backend.facade import api, contracts
from products.cross_project_dashboards.backend.models import CrossProjectDashboard
from products.product_analytics.backend.facade.models import Insight


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

    def test_soft_deleting_a_dashboard_logs_a_delete(self):
        dashboard = CrossProjectDashboard.objects.create(
            organization=self.organization, name="Overview", created_by=self.user
        )
        api.delete_dashboard(organization_id=self.organization.id, dashboard_id=dashboard.id, user=self.user)

        log = ActivityLog.objects.filter(scope="CrossProjectDashboard", item_id=str(dashboard.id)).latest("created_at")
        assert log.activity == "deleted"

    def test_tile_changes_log_on_the_dashboard_but_layout_moves_do_not(self):
        dashboard = CrossProjectDashboard.objects.create(
            organization=self.organization, name="Overview", created_by=self.user
        )
        insight = Insight.objects.create(team=self.team, name="Signups")
        scope = {"organization_id": self.organization.id, "dashboard_id": dashboard.id, "user": self.user}
        tile = api.create_tile(
            **scope,
            tile=contracts.NewTile(
                project_id=self.team.pk, insight_id=insight.pk, layouts={}, color=None, filters_overrides={}
            ),
        )
        moved = contracts.TileChanges(fields=frozenset({"layouts"}), layouts={"sm": {"x": 6}})
        api.update_tile(**scope, tile_id=tile.id, changes=moved)
        recolored = contracts.TileChanges(fields=frozenset({"color"}), color="red")
        api.update_tile(**scope, tile_id=tile.id, changes=recolored)
        api.delete_tile(**scope, tile_id=tile.id)

        logs = ActivityLog.objects.filter(
            scope="CrossProjectDashboard", item_id=str(dashboard.id), activity="updated"
        ).order_by("created_at")
        assert [(log.detail or {})["changes"][0]["action"] for log in logs] == ["created", "changed", "deleted"]
        assert all("project_id" not in str(log.detail) for log in logs)
