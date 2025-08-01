import os
from unittest.mock import Mock, patch

import pytest
import dagster
from posthog.models.web_preaggregated.team_selection import DEFAULT_ENABLED_TEAM_IDS

from dags.web_preaggregated_team_selection import (
    get_team_ids_from_sources,
    get_teams_from_env,
    get_teams_from_top_pageviews,
    get_teams_from_feature_enrollment,
    validate_team_ids,
    store_team_selection_in_clickhouse,
)


class TestGetTeamIdsFromSources:
    def setup_method(self):
        self.mock_context = Mock(spec=dagster.OpExecutionContext)
        self.mock_context.log = Mock()

    def test_returns_defaults_only_when_no_strategies_enabled(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": ""}, clear=True):
            result = get_team_ids_from_sources(self.mock_context)

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)
        assert isinstance(result, list)

    def test_includes_env_teams_when_env_strategy_enabled(self):
        with patch.dict(
            os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": "env", "WEB_ANALYTICS_ENABLED_TEAM_IDS": "123,456"}
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should include both env teams and defaults
        assert 123 in result
        assert 456 in result
        for default_team in DEFAULT_ENABLED_TEAM_IDS:
            assert default_team in result

    @patch("dags.web_preaggregated_team_selection.get_teams_from_top_pageviews")
    def test_includes_pageview_teams_when_pageviews_strategy_enabled(self, mock_pageviews):
        mock_pageviews.return_value = {999, 888}

        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": "most_pageviews"}):
            result = get_team_ids_from_sources(self.mock_context)

        assert 999 in result
        assert 888 in result
        mock_pageviews.assert_called_once_with(self.mock_context)

    def test_handles_invalid_env_teams_gracefully(self):
        with patch.dict(
            os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": "env", "WEB_ANALYTICS_ENABLED_TEAM_IDS": "invalid,123"}
        ):
            result = get_team_ids_from_sources(self.mock_context)

        # Should still include defaults even if env parsing fails
        assert set(DEFAULT_ENABLED_TEAM_IDS).issubset(set(result))

    def test_result_is_sorted_list(self):
        with patch.dict(
            os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": "env", "WEB_ANALYTICS_ENABLED_TEAM_IDS": "300,100,200"}
        ):
            result = get_team_ids_from_sources(self.mock_context)

        assert isinstance(result, list)
        assert result == sorted(result)

    @patch("dags.web_preaggregated_team_selection.get_teams_from_feature_enrollment")
    def test_includes_feature_enrollment_teams_when_strategy_enabled(self, mock_enrollment):
        mock_enrollment.return_value = {777, 666}

        with patch.dict(
            os.environ,
            {"WEB_ANALYTICS_TEAM_STRATEGIES": "feature_enrollment", "WEB_ANALYTICS_FEATURE_FLAG_KEY": "test-flag"},
        ):
            result = get_team_ids_from_sources(self.mock_context)

        assert 777 in result
        assert 666 in result
        mock_enrollment.assert_called_once_with(self.mock_context, "test-flag")

    @patch("dags.web_preaggregated_team_selection.get_teams_from_feature_enrollment")
    def test_uses_default_flag_key_when_not_specified(self, mock_enrollment):
        mock_enrollment.return_value = {555}

        with patch.dict(os.environ, {"WEB_ANALYTICS_TEAM_STRATEGIES": "feature_enrollment"}, clear=True):
            result = get_team_ids_from_sources(self.mock_context)

        assert 555 in result
        mock_enrollment.assert_called_once_with(self.mock_context, "web-analytics-api")

    @patch("dags.web_preaggregated_team_selection.get_teams_from_top_pageviews")
    @patch("dags.web_preaggregated_team_selection.get_teams_from_feature_enrollment")
    def test_combines_multiple_strategies(self, mock_enrollment, mock_pageviews):
        mock_enrollment.return_value = {111, 222}
        mock_pageviews.return_value = {333, 444}

        with patch.dict(
            os.environ,
            {
                "WEB_ANALYTICS_TEAM_STRATEGIES": "most_pageviews,feature_enrollment",
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
            {"WEB_ANALYTICS_TEAM_STRATEGIES": "env,invalid_strategy,most_pageviews,another_invalid"},
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


class TestHelperFunctions:
    def test_get_teams_from_env_returns_empty_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_teams_from_env()
        assert result == set()

    def test_get_teams_from_env_parses_valid_teams(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": "123,456,789"}):
            result = get_teams_from_env()
        assert result == {123, 456, 789}

    def test_get_teams_from_env_handles_invalid_teams(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": "invalid,123"}):
            result = get_teams_from_env()
        assert result == set()  # Should return empty on ValueError

    @patch("dags.web_preaggregated_team_selection.sync_execute")
    def test_get_teams_from_top_pageviews_returns_teams(self, mock_execute):
        mock_context = Mock()
        mock_context.log = Mock()
        mock_execute.return_value = [(123,), (456,)]

        result = get_teams_from_top_pageviews(mock_context)

        assert result == {123, 456}
        mock_execute.assert_called_once()

    @patch("dags.web_preaggregated_team_selection.sync_execute")
    def test_get_teams_from_top_pageviews_handles_errors(self, mock_execute):
        mock_context = Mock()
        mock_context.log = Mock()
        mock_execute.side_effect = Exception("DB error")

        result = get_teams_from_top_pageviews(mock_context)

        assert result == set()
        mock_context.log.warning.assert_called_once()

    @patch("posthog.models.person.person.Person.objects")
    def test_get_teams_from_feature_enrollment_returns_teams(self, mock_person_objects):
        mock_context = Mock()
        mock_context.log = Mock()

        # Mock the Django ORM query chain
        mock_queryset = Mock()
        mock_queryset.values_list.return_value.distinct.return_value = [1, 2, 3]
        mock_person_objects.filter.return_value = mock_queryset

        result = get_teams_from_feature_enrollment(mock_context, "test-flag")

        assert result == {1, 2, 3}
        mock_person_objects.filter.assert_called_once_with(**{"properties__$feature_enrollment/test-flag": True})
        mock_context.log.info.assert_called_once()

    @patch("posthog.models.person.person.Person.objects")
    def test_get_teams_from_feature_enrollment_handles_errors(self, mock_person_objects):
        mock_context = Mock()
        mock_context.log = Mock()
        mock_person_objects.filter.side_effect = Exception("DB error")

        result = get_teams_from_feature_enrollment(mock_context, "test-flag")

        assert result == set()
        mock_context.log.warning.assert_called_once_with(
            "Failed to get teams with feature enrollment for 'test-flag': DB error"
        )

    @patch("posthog.models.person.person.Person.objects")
    def test_get_teams_from_feature_enrollment_uses_default_flag_key(self, mock_person_objects):
        mock_context = Mock()
        mock_context.log = Mock()

        mock_queryset = Mock()
        mock_queryset.values_list.return_value.distinct.return_value = [5, 6]
        mock_person_objects.filter.return_value = mock_queryset

        result = get_teams_from_feature_enrollment(mock_context)  # No flag_key specified

        assert result == {5, 6}
        mock_person_objects.filter.assert_called_once_with(
            **{"properties__$feature_enrollment/web-analytics-enabled": True}
        )


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
