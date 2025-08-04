import os
from unittest.mock import Mock, patch

import pytest
import dagster
from posthog.models.web_preaggregated.team_selection import DEFAULT_ENABLED_TEAM_IDS

from dags.web_preaggregated_team_selection import (
    get_team_ids_from_sources,
    validate_team_ids,
    store_team_selection_in_clickhouse,
    web_analytics_team_selection,
)
from dags.web_preaggregated_team_selection_strategies import (
    EnvironmentVariableStrategy,
    HighPageviewsStrategy,
    FeatureEnrollmentStrategy,
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

    @patch("dags.web_preaggregated_team_selection_strategies.HighPageviewsStrategy.get_teams")
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

    @patch("dags.web_preaggregated_team_selection_strategies.FeatureEnrollmentStrategy.get_teams")
    def test_includes_feature_enrollment_teams_when_strategy_enabled(self, mock_enrollment):
        mock_enrollment.return_value = {777, 666}

        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "feature_enrollment",
                "WEB_ANALYTICS_FEATURE_FLAG_KEY": "test-flag",
            },
        ):
            result = get_team_ids_from_sources(self.mock_context)

        assert 777 in result
        assert 666 in result
        mock_enrollment.assert_called_once_with(self.mock_context)

    @patch("dags.web_preaggregated_team_selection_strategies.FeatureEnrollmentStrategy.get_teams")
    def test_uses_default_flag_key_when_not_specified(self, mock_enrollment):
        mock_enrollment.return_value = {555}

        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "feature_enrollment"}, clear=True):
            result = get_team_ids_from_sources(self.mock_context)

        assert 555 in result
        mock_enrollment.assert_called_once_with(self.mock_context)

    @patch("dags.web_preaggregated_team_selection_strategies.HighPageviewsStrategy.get_teams")
    @patch("dags.web_preaggregated_team_selection_strategies.FeatureEnrollmentStrategy.get_teams")
    def test_combines_multiple_strategies(self, mock_enrollment, mock_pageviews):
        mock_enrollment.return_value = {111, 222}
        mock_pageviews.return_value = {333, 444}

        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES": "high_pageviews,feature_enrollment",
                "WEB_ANALYTICS_ENABLED_TEAM_IDS": "555",
            },
            clear=True,
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include teams from all strategies plus defaults
        assert 111 in result  # from feature enrollment
        assert 222 in result  # from feature enrollment
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

    @patch("dags.web_preaggregated_team_selection_strategies.sync_execute")
    def test_high_pageviews_strategy_returns_teams(self, mock_execute):
        strategy = HighPageviewsStrategy()
        mock_execute.return_value = [(123,), (456,)]

        result = strategy.get_teams(self.mock_context)

        assert result == {123, 456}
        mock_execute.assert_called_once()

    @patch("dags.web_preaggregated_team_selection_strategies.sync_execute")
    def test_high_pageviews_strategy_handles_errors(self, mock_execute):
        strategy = HighPageviewsStrategy()
        mock_execute.side_effect = Exception("DB error")

        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.warning.assert_called_once()

    @patch("posthog.models.person.person.Person.objects")
    def test_feature_enrollment_strategy_returns_teams(self, mock_person_objects):
        strategy = FeatureEnrollmentStrategy()

        # Mock the Django ORM query chain
        mock_queryset = Mock()
        mock_queryset.values_list.return_value.distinct.return_value = [1, 2, 3]
        mock_person_objects.filter.return_value = mock_queryset

        result = strategy.get_teams(self.mock_context)

        assert result == {1, 2, 3}
        mock_person_objects.filter.assert_called_once_with(
            **{"properties__$feature_enrollment/web-analytics-api": True}
        )
        self.mock_context.log.info.assert_called_once()

    @patch("posthog.models.person.person.Person.objects")
    def test_feature_enrollment_strategy_handles_errors(self, mock_person_objects):
        strategy = FeatureEnrollmentStrategy()
        mock_person_objects.filter.side_effect = Exception("DB error")

        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.warning.assert_called_once()

    @patch("posthog.models.person.person.Person.objects")
    def test_feature_enrollment_strategy_uses_custom_flag_key(self, mock_person_objects):
        strategy = FeatureEnrollmentStrategy()

        mock_queryset = Mock()
        mock_queryset.values_list.return_value.distinct.return_value = [5, 6]
        mock_person_objects.filter.return_value = mock_queryset

        with patch.dict(os.environ, {"WEB_ANALYTICS_FEATURE_FLAG_KEY": "custom-flag"}):
            result = strategy.get_teams(self.mock_context)

        assert result == {5, 6}
        mock_person_objects.filter.assert_called_once_with(**{"properties__$feature_enrollment/custom-flag": True})


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
        team_ids = []

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
        assert result.metadata["team_count"] == len(test_teams)
        assert result.metadata["team_ids"] == str(test_teams)

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_handles_empty_teams(self, mock_store, mock_get_teams):
        empty_teams = []
        mock_get_teams.return_value = empty_teams
        mock_store.return_value = empty_teams

        context = dagster.build_asset_context()
        result = web_analytics_team_selection(context, self.mock_cluster)

        assert result.metadata["team_count"] == 0
        assert result.metadata["team_ids"] == str(empty_teams)

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_propagates_store_errors(self, mock_store, mock_get_teams):
        test_teams = [1, 2, 3]
        mock_get_teams.return_value = test_teams
        mock_store.side_effect = Exception("ClickHouse error")

        context = dagster.build_asset_context()

        with pytest.raises(Exception, match="ClickHouse error"):
            web_analytics_team_selection(context, self.mock_cluster)


class TestIntegrationScenarios:
    def test_complete_flow_with_env_variable(self):
        test_teams = "100, 200, 300"
        expected_teams = [100, 200, 300]

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources()

        assert result == expected_teams

    def test_complete_flow_with_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_team_ids_from_sources()

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)
        assert len(result) > 0  # Ensure defaults are not empty
