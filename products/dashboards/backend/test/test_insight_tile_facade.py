from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.dashboards.backend.facade.api import unknown_dashboard_ids
from products.dashboards.backend.models.dashboard import Dashboard


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
