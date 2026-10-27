from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
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

    @parameterized.expand(
        [
            ("revenue_analytics_config", "filter_test_accounts", True),
            ("marketing_analytics_config", "attribution_window_days", 14),
            ("customer_analytics_config", "account_group_type_index", 2),
            ("workflows_config", "capture_workflows_engagement_events", True),
            ("feature_flag_policy_config", "require_tags", True),
        ]
    )
    def test_team_accessor_loads_config_per_team_instance(self, accessor: str, field: str, new_value: Any) -> None:
        first_team = Team.objects.get(pk=self.team.pk)
        first_config = getattr(first_team, accessor)
        type(first_config).objects.filter(team_id=self.team.pk).update(**{field: new_value})
        second_team = Team.objects.get(pk=self.team.pk)

        second_config = getattr(second_team, accessor)

        assert second_config.team is second_team
        assert getattr(second_config, field) == new_value
