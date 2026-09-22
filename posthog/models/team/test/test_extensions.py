from posthog.test.base import BaseTest

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig


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
