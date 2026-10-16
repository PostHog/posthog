from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.user_home_settings import UserHomeSettings

from products.dashboards.backend.facade.api import home_dashboard_insights
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

OVERRIDE = {"date_from": "-7d"}


class TestHomeDashboardInsights(APIBaseTest):
    def _dashboard(self, name: str, short_ids: list[str]) -> Dashboard:
        dashboard = Dashboard.objects.create(
            team=self.team, name=name, filters={"properties": [{"key": "plan"}]}, variables={"v1": {"value": "pro"}}
        )
        for row, short_id in reversed(list(enumerate(short_ids))):
            insight = Insight.objects.create(team=self.team, short_id=short_id, deleted=short_id.startswith("gone"))
            DashboardTile.objects.create(
                dashboard=dashboard,
                insight=insight,
                layouts={"sm": {"x": 0, "y": row * 5, "w": 6, "h": 5}},
                filters_overrides=OVERRIDE if short_id.endswith("2") else None,
            )
        return dashboard

    @parameterized.expand(
        [
            ("the homepage dashboard", True, True, "home", [("h1", None), ("h2", OVERRIDE)]),
            ("the project dashboard without a homepage", False, True, "primary", [("p1", None), ("p2", OVERRIDE)]),
            ("nothing without either", False, False, None, None),
        ]
    )
    def test_the_home_dashboard_lists_its_live_insights_in_layout_order(
        self,
        _name: str,
        homepage: bool,
        primary: bool,
        expected_dashboard: str | None,
        expected: list[tuple[str, dict[str, Any] | None]] | None,
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
            (
                found.dashboard_id,
                [(t.insight_short_id, t.filters_overrides) for t in found.tiles],
                found.filters,
                found.variables,
            )
            if found
            else None,
            (dashboards[expected_dashboard].id, expected, {"properties": [{"key": "plan"}]}, {"v1": {"value": "pro"}})
            if expected_dashboard
            else None,
        )
