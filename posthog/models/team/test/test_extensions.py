from posthog.test.base import BaseTest

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig


class TestGetOrCreateTeamExtension(BaseTest):
    def test_existing_extension_does_not_reload_team(self) -> None:
        # Ensure we go through the get() branch with the config already present.
        TeamRevenueAnalyticsConfig.objects.get_or_create(team=self.team)

        config = get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        # Accessing `.team` must read back the in-memory team without a fresh query — this guards
        # the redundant Team reload on the actors/cohort cache-key hot path (to_cache_key_dict).
        assert config.team is self.team
        with self.assertNumQueries(0):
            _ = config.team.base_currency

    def test_created_extension_does_not_reload_team(self) -> None:
        TeamRevenueAnalyticsConfig.objects.filter(team=self.team).delete()

        config = get_or_create_team_extension(self.team, TeamRevenueAnalyticsConfig)

        assert config.team is self.team
        with self.assertNumQueries(0):
            _ = config.team.base_currency
