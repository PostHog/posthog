from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import Mock

from posthog.models import Team
from posthog.models.web_preaggregated.team_selection_strategies import ProjectSettingsStrategy


class TestProjectSettingsStrategyIntegration(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.mock_context = Mock()
        self.mock_context.log = Mock()

    def test_returns_teams_with_web_analytics_pre_aggregated_tables_enabled_from_database(self):
        # Create test teams with different web_analytics_pre_aggregated_tables_enabled states
        enabled_team_1 = Team.objects.create(
            organization=self.organization, name="Enabled Team 1", web_analytics_pre_aggregated_tables_enabled=True
        )
        enabled_team_2 = Team.objects.create(
            organization=self.organization, name="Enabled Team 2", web_analytics_pre_aggregated_tables_enabled=True
        )
        disabled_team = Team.objects.create(
            organization=self.organization, name="Disabled Team", web_analytics_pre_aggregated_tables_enabled=False
        )

        # Default team from APIBaseTest setup (should be False by default)
        assert not self.team.web_analytics_pre_aggregated_tables_enabled

        strategy = ProjectSettingsStrategy()
        result = strategy.get_teams(self.mock_context)

        # Should only include teams with web_analytics_pre_aggregated_tables_enabled=True
        expected_teams = {enabled_team_1.pk, enabled_team_2.pk}
        assert result == expected_teams

        # Should not include disabled teams
        assert disabled_team.pk not in result
        assert self.team.pk not in result  # Default team is disabled

        # Verify correct logging
        self.mock_context.log.info.assert_called_with("Found 2 teams with web analytics enabled in project settings")

    def test_returns_empty_set_when_no_teams_enabled(self):
        # Create teams with web_analytics_pre_aggregated_tables_enabled=False
        Team.objects.create(
            organization=self.organization, name="Disabled Team 1", web_analytics_pre_aggregated_tables_enabled=False
        )
        Team.objects.create(
            organization=self.organization, name="Disabled Team 2", web_analytics_pre_aggregated_tables_enabled=False
        )

        strategy = ProjectSettingsStrategy()
        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.info.assert_called_with("Found 0 teams with web analytics enabled in project settings")

    def test_updates_team_setting_and_strategy_reflects_change(self):
        strategy = ProjectSettingsStrategy()

        # Initially no teams enabled
        result = strategy.get_teams(self.mock_context)
        assert result == set()

        # Enable web analytics for the team
        self.team.web_analytics_pre_aggregated_tables_enabled = True
        self.team.save()

        # Strategy should now pick up this team
        result = strategy.get_teams(self.mock_context)
        assert result == {self.team.pk}

        # Disable it again
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()

        # Strategy should no longer include this team
        result = strategy.get_teams(self.mock_context)
        assert result == set()
