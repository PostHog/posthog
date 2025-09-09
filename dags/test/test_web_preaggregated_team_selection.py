import os

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import dagster

from posthog.models.team.team import Team
from posthog.models.web_preaggregated.team_selection import DEFAULT_ENABLED_TEAM_IDS
from posthog.models.web_preaggregated.team_selection_strategies import (
    EnvironmentVariableStrategy,
    HighPageviewsStrategy,
    ProjectSettingsStrategy,
)

from dags.web_preaggregated_team_selection import (
    get_team_ids_from_sources,
    store_team_selection_in_clickhouse,
    validate_team_ids,
    web_analytics_team_selection,
)


class TestGetTeamIdsFromSources:
    def setup_method(self):
        self.mock_context = Mock(spec=dagster.OpExecutionContext)
        self.mock_context.log = Mock()

    def test_returns_defaults_only_when_no_strategies_enabled(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": ""}, clear=True):
            result = get_team_ids_from_sources(self.mock_context)

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)
        assert isinstance(result, list)

    def test_includes_env_teams_when_env_strategy_enabled(self):
        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "environment_variable",
                "WEB_ANALYTICS_ENABLED_TEAM_IDS": "123,456",
            },
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include both env teams and defaults
        assert 123 in result
        assert 456 in result
        for default_team in DEFAULT_ENABLED_TEAM_IDS:
            assert default_team in result

    @patch("posthog.models.web_preaggregated.team_selection_strategies.HighPageviewsStrategy.get_teams")
    def test_includes_pageview_teams_when_pageviews_strategy_enabled(self, mock_pageviews):
        mock_pageviews.return_value = {999, 888}

        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "high_pageviews"}):
            result = get_team_ids_from_sources(self.mock_context)

        assert 999 in result
        assert 888 in result
        mock_pageviews.assert_called_once_with(self.mock_context)

    def test_handles_invalid_env_teams_gracefully(self):
        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "environment_variable",
                "WEB_ANALYTICS_ENABLED_TEAM_IDS": "invalid,123",
            },
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should still include defaults even if env parsing fails
        assert set(DEFAULT_ENABLED_TEAM_IDS).issubset(set(result))

    def test_result_is_sorted_list(self):
        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "environment_variable",
                "WEB_ANALYTICS_ENABLED_TEAM_IDS": "300,100,200",
            },
        ):
            result = get_team_ids_from_sources(self.mock_context)

        assert isinstance(result, list)
        assert result == sorted(result)

    @patch("posthog.models.web_preaggregated.team_selection_strategies.ProjectSettingsStrategy.get_teams")
    def test_includes_project_settings_teams_when_strategy_enabled(self, mock_project_settings):
        mock_project_settings.return_value = {888, 999}

        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "project_settings",
            },
        ):
            result = get_team_ids_from_sources(self.mock_context)

        assert 888 in result
        assert 999 in result
        mock_project_settings.assert_called_once_with(self.mock_context)

    @patch("posthog.models.web_preaggregated.team_selection_strategies.HighPageviewsStrategy.get_teams")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.ProjectSettingsStrategy.get_teams")
    def test_combines_multiple_strategies(self, mock_project_settings, mock_pageviews):
        mock_project_settings.return_value = {111, 222}
        mock_pageviews.return_value = {333, 444}

        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "high_pageviews,project_settings",
                "WEB_ANALYTICS_ENABLED_TEAM_IDS": "555",
            },
            clear=True,
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include teams from all strategies plus defaults
        assert 111 in result  # from project settings
        assert 222 in result  # from project settings
        assert 333 in result  # from pageviews
        assert 444 in result  # from pageviews
        for default_team in DEFAULT_ENABLED_TEAM_IDS:
            assert default_team in result

    def test_ignores_invalid_strategies(self):
        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "environment_variable,invalid_strategy,high_pageviews,another_invalid"
            },
            clear=True,
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should warn about invalid strategies
        self.mock_context.log.warning.assert_called()
        # Should still include defaults
        for default_team in DEFAULT_ENABLED_TEAM_IDS:
            assert default_team in result


class TestValidation:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log = Mock()

    @patch("posthog.models.team.team.Team.objects")
    def test_validate_team_ids_filters_invalid_teams(self, mock_team_objects):
        mock_team_objects.filter.return_value.values_list.return_value = [1, 2, 3]

        result = validate_team_ids(self.mock_context, {1, 2, 3, 999, 888})

        assert result == {1, 2, 3}
        self.mock_context.log.warning.assert_called_once()
        self.mock_context.log.info.assert_called_once()

    @patch("posthog.models.team.team.Team.objects")
    def test_validate_team_ids_handles_db_errors(self, mock_team_objects):
        mock_team_objects.filter.side_effect = Exception("DB error")

        original_teams = {1, 2, 3}
        result = validate_team_ids(self.mock_context, original_teams)

        assert result == original_teams  # Should return original on error
        self.mock_context.log.warning.assert_called_once()

    def test_validate_team_ids_handles_empty_input(self):
        result = validate_team_ids(self.mock_context, set())
        assert result == set()


class TestStrategyClasses:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log = Mock()

    def test_environment_variable_strategy_returns_empty_when_no_env(self):
        strategy = EnvironmentVariableStrategy()
        with patch.dict(os.environ, {}, clear=True):
            result = strategy.get_teams(self.mock_context)
        assert result == set()

    def test_environment_variable_strategy_parses_valid_teams(self):
        strategy = EnvironmentVariableStrategy()
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": "123,456,789"}):
            result = strategy.get_teams(self.mock_context)
        assert result == {123, 456, 789}

    def test_environment_variable_strategy_handles_invalid_and_valid_teams(self):
        strategy = EnvironmentVariableStrategy()
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": "invalid,123,not_a_number,456"}):
            result = strategy.get_teams(self.mock_context)
        assert result == {123, 456}  # Should include valid ones only
        self.mock_context.log.warning.assert_called_once()

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    def test_high_pageviews_strategy_returns_teams(self, mock_execute):
        strategy = HighPageviewsStrategy()
        mock_execute.return_value = [(123,), (456,)]

        result = strategy.get_teams(self.mock_context)

        assert result == {123, 456}
        mock_execute.assert_called_once()

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    def test_high_pageviews_strategy_handles_errors(self, mock_execute):
        strategy = HighPageviewsStrategy()
        mock_execute.side_effect = Exception("DB error")

        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.warning.assert_called_once()

    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team.objects")
    def test_project_settings_strategy_returns_teams(self, mock_team_objects):
        strategy = ProjectSettingsStrategy()
        mock_team_objects.filter.return_value.values_list.return_value = [123, 456]

        result = strategy.get_teams(self.mock_context)

        assert result == {123, 456}
        mock_team_objects.filter.assert_called_once_with(web_analytics_pre_aggregated_tables_enabled=True)
        mock_team_objects.filter.return_value.values_list.assert_called_once_with("id", flat=True)

    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team.objects")
    def test_project_settings_strategy_handles_database_errors(self, mock_team_objects):
        strategy = ProjectSettingsStrategy()
        mock_team_objects.filter.side_effect = Exception("Database error")

        result = strategy.get_teams(self.mock_context)

        assert result == set()

    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team.objects")
    def test_project_settings_strategy_handles_empty_results(self, mock_team_objects):
        strategy = ProjectSettingsStrategy()
        mock_team_objects.filter.return_value.values_list.return_value = []

        result = strategy.get_teams(self.mock_context)

        assert result == set()


class TestStoreTeamSelectionInClickhouse:
    def setup_method(self):
        self.mock_context = Mock(spec=dagster.OpExecutionContext)
        self.mock_context.log = Mock()
        self.mock_cluster = Mock()

    def test_stores_team_selection_successfully(self):
        team_ids = [1, 2, 3]

        # Mock successful operations
        insert_results = {"host1": True, "host2": True}
        reload_results = {"host1": True, "host2": True}

        self.mock_cluster.map_all_hosts.side_effect = [
            Mock(result=Mock(return_value=insert_results)),
            Mock(result=Mock(return_value=reload_results)),
        ]

        result = store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

        assert result == team_ids
        assert self.mock_cluster.map_all_hosts.call_count == 2
        self.mock_context.log.info.assert_called()

    def test_handles_empty_team_ids_list(self):
        team_ids: list[int] = []

        result = store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

        assert result == []
        self.mock_context.log.warning.assert_called_with("No team IDs to store")
        # Should not call cluster operations for empty list
        self.mock_cluster.map_all_hosts.assert_not_called()

    def test_raises_exception_on_insert_failure(self):
        team_ids = [1, 2, 3]

        # Mock failed insert on one host
        insert_results = {"host1": True, "host2": False}
        reload_results = {"host1": True, "host2": True}

        self.mock_cluster.map_all_hosts.side_effect = [
            Mock(result=Mock(return_value=insert_results)),
            Mock(result=Mock(return_value=reload_results)),
        ]

        with pytest.raises(Exception, match="Failed to insert team selection"):
            store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

    def test_raises_exception_on_dictionary_reload_failure(self):
        team_ids = [1, 2, 3]

        # Mock failed reload on one host
        insert_results = {"host1": True, "host2": True}
        reload_results = {"host1": True, "host2": False}

        self.mock_cluster.map_all_hosts.side_effect = [
            Mock(result=Mock(return_value=insert_results)),
            Mock(result=Mock(return_value=reload_results)),
        ]

        with pytest.raises(Exception, match="Failed to reload dictionary"):
            store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

    def test_logs_appropriate_messages(self):
        team_ids = [1, 2, 3]

        # Mock successful operations
        insert_results = {"host1": True, "host2": True}
        reload_results = {"host1": True, "host2": True}

        self.mock_cluster.map_all_hosts.side_effect = [
            Mock(result=Mock(return_value=insert_results)),
            Mock(result=Mock(return_value=reload_results)),
        ]

        store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

        self.mock_context.log.info.assert_called_with(f"Storing {len(team_ids)} enabled team IDs in ClickHouse")

    def test_calls_cluster_map_all_hosts_twice(self):
        team_ids = [1, 2, 3]

        # Mock successful operations
        insert_results = {"host1": True}
        reload_results = {"host1": True}

        self.mock_cluster.map_all_hosts.side_effect = [
            Mock(result=Mock(return_value=insert_results)),
            Mock(result=Mock(return_value=reload_results)),
        ]

        store_team_selection_in_clickhouse(self.mock_context, team_ids, self.mock_cluster)

        # Verify map_all_hosts was called twice (once for insert, once for reload)
        assert self.mock_cluster.map_all_hosts.call_count == 2


class TestWebAnalyticsTeamSelectionAsset:
    def setup_method(self):
        self.mock_context = Mock(spec=dagster.AssetExecutionContext)
        self.mock_context.log = Mock()
        self.mock_cluster = Mock()

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_execution_success(self, mock_store, mock_get_teams):
        test_teams = [1, 2, 3]
        mock_get_teams.return_value = test_teams
        mock_store.return_value = test_teams

        context = dagster.build_asset_context()

        result = web_analytics_team_selection(context, self.mock_cluster)

        # Verify functions were called
        mock_get_teams.assert_called_once()
        mock_store.assert_called_once_with(context, test_teams, self.mock_cluster)

        # Verify result
        assert isinstance(result, dagster.MaterializeResult)
        metadata = result.metadata
        assert metadata is not None
        assert metadata["team_count"] == len(test_teams)
        assert metadata["team_ids"] == str(test_teams)

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_handles_empty_teams(self, mock_store, mock_get_teams):
        empty_teams: list[int] = []
        mock_get_teams.return_value = empty_teams
        mock_store.return_value = empty_teams

        context = dagster.build_asset_context()
        result = web_analytics_team_selection(context, self.mock_cluster)

        assert isinstance(result, dagster.MaterializeResult)
        metadata = result.metadata
        assert metadata is not None
        assert metadata["team_count"] == 0
        assert metadata["team_ids"] == str(empty_teams)

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_propagates_store_errors(self, mock_store, mock_get_teams):
        test_teams = [1, 2, 3]
        mock_get_teams.return_value = test_teams
        mock_store.side_effect = Exception("ClickHouse error")

        context = dagster.build_asset_context()

        with pytest.raises(Exception, match="ClickHouse error"):
            web_analytics_team_selection(context, self.mock_cluster)


class TestIntegrationScenarios(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.mock_context = Mock(spec=dagster.OpExecutionContext)
        self.mock_context.log = Mock()

    @patch("dags.web_preaggregated_team_selection.validate_team_ids")
    def test_complete_flow_with_env_variable(self, mock_validate):
        test_teams = "100, 200, 300"
        expected_teams = [100, 200, 300, *list(DEFAULT_ENABLED_TEAM_IDS)]
        mock_validate.return_value = set(expected_teams)

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include env teams plus defaults
        assert 100 in result
        assert 200 in result
        assert 300 in result
        for default_team in DEFAULT_ENABLED_TEAM_IDS:
            assert default_team in result

    @patch("dags.web_preaggregated_team_selection.validate_team_ids")
    def test_complete_flow_with_defaults(self, mock_validate):
        mock_validate.return_value = set(DEFAULT_ENABLED_TEAM_IDS)

        with patch.dict(os.environ, {}, clear=True):
            result = get_team_ids_from_sources(self.mock_context)

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)
        assert len(result) > 0  # Ensure defaults are not empty

    @patch("dags.web_preaggregated_team_selection.validate_team_ids")
    def test_complete_flow_with_project_settings_from_database(self, mock_validate):
        # Create teams with different web analytics settings
        enabled_team_1 = Team.objects.create(
            organization=self.organization,
            name="Analytics Enabled Team 1",
            web_analytics_pre_aggregated_tables_enabled=True,
        )
        enabled_team_2 = Team.objects.create(
            organization=self.organization,
            name="Analytics Enabled Team 2",
            web_analytics_pre_aggregated_tables_enabled=True,
        )
        disabled_team = Team.objects.create(
            organization=self.organization,
            name="Analytics Disabled Team",
            web_analytics_pre_aggregated_tables_enabled=False,
        )

        # Mock validation to allow our test teams
        expected_enabled_teams = [enabled_team_1.pk, enabled_team_2.pk]
        all_teams = expected_enabled_teams + list(DEFAULT_ENABLED_TEAM_IDS)
        mock_validate.return_value = set(all_teams)

        # Test the full DAG flow using project_settings strategy
        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "project_settings"}):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include teams with web_analytics_pre_aggregated_tables_enabled=True + defaults
        assert enabled_team_1.pk in result
        assert enabled_team_2.pk in result
        assert disabled_team.pk not in result  # Should NOT include disabled team

        # Should also include defaults
        assert set(DEFAULT_ENABLED_TEAM_IDS).issubset(set(result))

        # Verify result is sorted list
        assert result == sorted(result)
