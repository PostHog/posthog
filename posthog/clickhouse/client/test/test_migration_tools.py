from unittest.mock import Mock, patch

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


@patch("posthog.clickhouse.client.migration_tools.get_migrations_cluster")
def test_run_sql_with_exceptions(mock_get_cluster):
    mock_cluster = Mock()
    mock_get_cluster.return_value = mock_cluster

    # Test 1: NodeRole.ALL with replicated table
    sql_replicated = "ALTER TABLE foo ON CLUSTER 'cluster'"
    run_sql_with_exceptions(sql_replicated, node_role=NodeRole.ALL).apply("dummy_database")

    assert mock_cluster.any_host.call_count == 1
    mock_cluster.reset_mock()

    # Test 2: NodeRole.ALL with non-replicated table
    sql_non_replicated = "ALTER TABLE foo"
    run_sql_with_exceptions(sql_non_replicated, node_role=NodeRole.ALL)

    assert mock_cluster.map_all_hosts.call_count == 1
    mock_cluster.reset_mock()
