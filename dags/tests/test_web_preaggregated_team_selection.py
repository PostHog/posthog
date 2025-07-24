import os
from unittest.mock import Mock, patch

import pytest
import dagster
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.team_selection import (
    DEFAULT_ENABLED_TEAM_IDS,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME,
)
from posthog.clickhouse.cluster import ClickhouseCluster
from dagster import build_asset_context, build_op_context

from dags.web_preaggregated_team_selection import (
    get_team_ids_from_sources,
    store_team_selection_in_clickhouse,
    web_analytics_team_selection,
)


class TestGetTeamIdsFromSources:
    def test_returns_default_teams_when_no_env_set(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_team_ids_from_sources()

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)

    def test_returns_teams_from_env_variable(self):
        test_teams = "123, 456, 789"
        expected = [123, 456, 789]

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources()

        assert result == expected

    def test_handles_single_team_in_env(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": "42"}):
            result = get_team_ids_from_sources()

        assert result == [42]

    def test_strips_whitespace_from_env_teams(self):
        test_teams = " 111 , 222 , 333 "
        expected = [111, 222, 333]

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources()

        assert result == expected

    def test_removes_duplicates_from_env_teams(self):
        test_teams = "100, 200, 100, 300, 200"
        expected = [100, 200, 300]

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources()

        assert result == expected

    def test_ignores_invalid_team_ids_in_env(self):
        invalid_teams = "not_a_number, abc, 123.45"

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": invalid_teams}):
            result = get_team_ids_from_sources()

        # Should fall back to defaults since all env values are invalid
        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)

    def test_handles_mixed_valid_invalid_team_ids(self):
        mixed_teams = "123, invalid, 456, not_a_number"

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": mixed_teams}):
            result = get_team_ids_from_sources()

        # Should fall back to defaults since ValueError is raised
        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)

    def test_handles_empty_env_variable(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": ""}):
            result = get_team_ids_from_sources()

        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)

    def test_handles_env_variable_with_only_commas(self):
        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": ",,, ,"}):
            result = get_team_ids_from_sources()

        # Empty strings will cause ValueError when converting to int
        assert result == sorted(DEFAULT_ENABLED_TEAM_IDS)

    def test_returns_sorted_team_ids(self):
        test_teams = "300, 100, 200"
        expected = [100, 200, 300]

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_teams}):
            result = get_team_ids_from_sources()

        assert result == expected


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

        # Import and use the function directly, not as an asset
        from dags.web_preaggregated_team_selection import web_analytics_team_selection

        # Create a proper Dagster context
        from dagster import build_asset_context

        context = build_asset_context()

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

        context = build_asset_context()
        result = web_analytics_team_selection(context, self.mock_cluster)

        assert result.metadata["team_count"] == 0
        assert result.metadata["team_ids"] == str(empty_teams)

    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    def test_asset_propagates_store_errors(self, mock_store, mock_get_teams):
        test_teams = [1, 2, 3]
        mock_get_teams.return_value = test_teams
        mock_store.side_effect = Exception("ClickHouse error")

        context = build_asset_context()

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

    @patch("dags.web_preaggregated_team_selection.store_team_selection_in_clickhouse")
    @patch("dags.web_preaggregated_team_selection.get_team_ids_from_sources")
    def test_web_analytics_asset_integration(self, mock_get_teams, mock_store):
        test_teams = [100, 200, 300]
        mock_get_teams.return_value = test_teams
        mock_store.return_value = test_teams

        mock_cluster = Mock()
        context = build_asset_context()
        result = web_analytics_team_selection(context, mock_cluster)

        assert isinstance(result, dagster.MaterializeResult)
        assert result.metadata["team_count"] == 3
        assert result.metadata["team_ids"] == str(test_teams)

        mock_get_teams.assert_called_once()
        mock_store.assert_called_once_with(context, test_teams, mock_cluster)


def test_team_selection_clickhouse_integration(cluster: ClickhouseCluster):
    test_team_ids = [123, 456, 789]
    context = build_op_context()

    with patch("dags.web_preaggregated_team_selection.settings_with_log_comment") as mock_settings:
        mock_settings.return_value = {"log_comment": "test"}

        result = store_team_selection_in_clickhouse(context, test_team_ids, cluster)
        assert result == test_team_ids

        query_result = sync_execute(
            f"SELECT team_id FROM {WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME} WHERE team_id IN %(team_ids)s ORDER BY team_id",
            {"team_ids": test_team_ids},
        )

        inserted_team_ids = [row[0] for row in query_result]
        assert inserted_team_ids == sorted(test_team_ids)

        dict_exists = sync_execute(
            f"SELECT 1 FROM system.dictionaries WHERE name = '{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}'"
        )
        assert len(dict_exists) > 0


def test_web_analytics_asset_real_execution(cluster: ClickhouseCluster):
    test_team_ids_str = "111,222,333"

    with patch("dags.web_preaggregated_team_selection.settings_with_log_comment") as mock_settings:
        mock_settings.return_value = {"log_comment": "test"}

        with patch.dict(os.environ, {"WEB_ANALYTICS_ENABLED_TEAM_IDS": test_team_ids_str}):
            context = build_asset_context()
            result = web_analytics_team_selection(context, cluster)

            assert isinstance(result, dagster.MaterializeResult)
            assert result.metadata["team_count"] == 3

            query_result = sync_execute(
                "SELECT COUNT(*) FROM web_pre_aggregated_teams WHERE team_id IN %(team_ids)s",
                {"team_ids": [111, 222, 333]},
            )

            assert query_result[0][0] == 3
