from posthog.test.base import BaseTest

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig


class TestGetOrCreateTeamExtension(BaseTest):
    def test_returned_config_reuses_team_without_extra_query(self) -> None:
        # The signal already created the config, so this hits the get() branch.
        config = get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        # Reverse relation must be back-populated so the query cache-key hot path
        # (to_cache_key_dict -> self.team.base_currency) resolves in memory.
        with self.assertNumQueries(0):
            assert config.team is self.team
            _ = config.to_cache_key_dict()

    def test_lazily_created_config_reuses_team_without_extra_query(self) -> None:
        TeamRevenueAnalyticsConfig.objects.filter(team=self.team).delete()

        config = get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        with self.assertNumQueries(0):
            assert config.team is self.team
