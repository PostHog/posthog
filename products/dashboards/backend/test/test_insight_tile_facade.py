from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.dashboards.backend.facade.api import DashboardRef, dashboards_by_insight, unknown_dashboard_ids
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


class TestUnknownDashboardIds(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.live = Dashboard.objects.create(team=self.team, name="live")
        self.soft_deleted = Dashboard.objects.create(team=self.team, name="gone", deleted=True)
        other_team = Team.objects.create(organization=self.organization)
        self.other_team_dashboard = Dashboard.objects.create(team=other_team, name="theirs")

    @parameterized.expand(
        [
            ("live_dashboard", "live", []),
            ("soft_deleted_dashboard", "soft_deleted", ["soft_deleted"]),
            ("another_teams_dashboard", "other_team_dashboard", ["other_team_dashboard"]),
        ]
    )
    def test_reports_ids_this_team_cannot_place_a_tile_on(
        self, _name: str, dashboard_attr: str, expected_unknown_attrs: list[str]
    ) -> None:
        dashboard_id = getattr(self, dashboard_attr).id
        expected = [getattr(self, attr).id for attr in expected_unknown_attrs]

        assert unknown_dashboard_ids([dashboard_id], team_id=self.team.id) == expected

    def test_reports_an_id_that_does_not_exist(self) -> None:
        assert unknown_dashboard_ids([self.live.id, 9_999_999], team_id=self.team.id) == [9_999_999]

    def test_reports_a_repeated_unknown_id_once(self) -> None:
        assert unknown_dashboard_ids([9_999_999, 9_999_999], team_id=self.team.id) == [9_999_999]


class TestDashboardsByInsight(APIBaseTest):
    def test_maps_live_insights_to_their_listed_live_dashboards_in_tile_order(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Signup funnel")
        deleted_insight = Insight.objects.create(team=self.team, name="gone", deleted=True)
        first = Dashboard.objects.create(team=self.team, name="Growth overview")
        second = Dashboard.objects.create(team=self.team, name="Quality review")
        for dashboard in (
            second,
            first,
            Dashboard.objects.create(team=self.team, name="gone", deleted=True),
            Dashboard.objects.create(team=self.team, name="embedded", creation_mode="unlisted"),
        ):
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        hidden_tile = Dashboard.objects.create(team=self.team, name="tile removed")
        DashboardTile.objects.create(dashboard=hidden_tile, insight=insight, deleted=True)
        DashboardTile.objects.create(dashboard=first, insight=deleted_insight)
        other_team = Team.objects.create(organization=self.organization)

        assert dashboards_by_insight([insight.id, deleted_insight.id], team_id=self.team.id) == {
            insight.id: (
                DashboardRef(id=second.id, name="Quality review"),
                DashboardRef(id=first.id, name="Growth overview"),
            )
        }
        assert dashboards_by_insight([insight.id], team_id=other_team.id) == {}
