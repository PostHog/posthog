from posthog.test.base import BaseTest

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.team_home_tab_dashboard import TeamHomeTabDashboard


class TestGetOrCreateTeamExtension(BaseTest):
    def test_reuses_loaded_team_without_refetching(self) -> None:
        # Prime the row so the second call takes the get() (not create()) path.
        get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        config = get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        # The config's team FK must be populated with the team we passed in, so reads such as
        # to_cache_key_dict()'s base_currency don't fire a fresh Team query per config.
        with self.assertNumQueries(0):
            assert config.team is self.team
            config.to_cache_key_dict()


class TestHomeTabDashboardProperty(BaseTest):
    def test_round_trips_through_extension_table_without_touching_primary_dashboard(self) -> None:
        primary_dashboard_before = self.team.primary_dashboard
        dashboard = Dashboard.objects.create(name="Home tab dashboard", team=self.team)

        self.team.home_tab_dashboard = dashboard

        self.assertEqual(self.team.home_tab_dashboard, dashboard)
        self.assertEqual(TeamHomeTabDashboard.objects.get(team=self.team).dashboard, dashboard)
        self.assertEqual(self.team.primary_dashboard, primary_dashboard_before)

    def test_defaults_to_none_when_no_row_exists(self) -> None:
        self.assertIsNone(self.team.home_tab_dashboard)
