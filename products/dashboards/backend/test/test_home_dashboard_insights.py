from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.user_home_settings import UserHomeSettings

from products.dashboards.backend.facade.api import home_dashboard_insights
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


class TestHomeDashboardInsights(APIBaseTest):
    def _dashboard(self, name: str, short_ids: list[str]) -> Dashboard:
        dashboard = Dashboard.objects.create(team=self.team, name=name, filters={"properties": [{"key": "plan"}]})
        for short_id in short_ids:
            insight = Insight.objects.create(team=self.team, short_id=short_id, deleted=short_id.startswith("gone"))
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        return dashboard

    @parameterized.expand(
        [
            ("the homepage dashboard", True, True, "home", ("h1", "h2")),
            ("the project dashboard without a homepage", False, True, "primary", ("p1", "p2")),
            ("nothing without either", False, False, None, None),
        ]
    )
    def test_the_home_dashboard_lists_its_live_insights_in_tile_order(
        self, _name: str, homepage: bool, primary: bool, expected_dashboard: str | None, expected: tuple | None
    ) -> None:
        dashboards = {
            "home": self._dashboard("Home", ["h1", "gone-h", "h2", "h3"]),
            "primary": self._dashboard("Main", ["p1", "p2"]),
        }
        if homepage:
            UserHomeSettings.objects.create(
                team=self.team,
                user=self.user,
                homepage={"pathname": f"/project/{self.team.id}/dashboard/{dashboards['home'].id}"},
            )
        self.team.primary_dashboard = dashboards["primary"] if primary else None
        self.team.save()

        found = home_dashboard_insights(team=self.team, user=self.user, limit=2)

        self.assertEqual(
            (found.dashboard_id, found.insight_short_ids, found.filters) if found else None,
            (dashboards[expected_dashboard].id, expected, {"properties": [{"key": "plan"}]})
            if expected_dashboard
            else None,
        )
