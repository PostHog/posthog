import unittest
from unittest import mock

from parameterized import parameterized

from posthog.clickhouse.client.connection import DATA_NODE_ROLES, SINGLE_SHARD_DATA_NODE_ROLES, NodeRole
from posthog.clickhouse.client.migration_tools import SkipIfTableMissing, run_sql_with_exceptions
from posthog.clickhouse.cluster import ClickhouseCluster, Query


class TestAlterReplicatedValidation(unittest.TestCase):
    def test_metadata_attached_to_operations(self):
        """Test that run_sql_with_exceptions attaches metadata correctly."""
        sql = "ALTER TABLE test_table ADD COLUMN test_col String"
        node_roles = [NodeRole.DATA]

        operation = run_sql_with_exceptions(
            sql=sql,
            node_roles=node_roles,
            sharded=False,
            is_alter_on_replicated_table=True,
        )

        # Check that metadata is attached
        self.assertTrue(hasattr(operation, "_sql"))
        self.assertTrue(hasattr(operation, "_node_roles"))
        self.assertTrue(hasattr(operation, "_sharded"))
        self.assertTrue(hasattr(operation, "_is_alter_on_replicated_table"))

        # Check values
        self.assertEqual(operation._sql, sql)
        self.assertEqual(operation._node_roles, node_roles)
        self.assertEqual(operation._sharded, False)
        self.assertEqual(operation._is_alter_on_replicated_table, True)

    def test_metadata_with_default_values(self):
        """Test that run_sql_with_exceptions attaches metadata with default values."""
        sql = "CREATE TABLE test_table (id UInt64) ENGINE = MergeTree()"

        operation = run_sql_with_exceptions(sql=sql)

        # Check that metadata is attached with defaults
        self.assertEqual(operation._sql, sql)
        self.assertEqual(operation._node_roles, [NodeRole.DATA])  # Default value
        self.assertEqual(operation._sharded, None)
        self.assertEqual(operation._is_alter_on_replicated_table, None)

    def test_metadata_with_sharded_table(self):
        """Test that run_sql_with_exceptions attaches metadata for sharded tables."""
        sql = "ALTER TABLE sharded_events ADD COLUMN test_col String"

        operation = run_sql_with_exceptions(
            sql=sql,
            node_roles=[NodeRole.DATA],
            sharded=True,
            is_alter_on_replicated_table=False,
        )

        self.assertEqual(operation._sharded, True)
        self.assertEqual(operation._is_alter_on_replicated_table, False)


def _build_cluster_mock() -> mock.MagicMock:
    cluster = mock.MagicMock()
    for method in ("map_one_host_per_shard", "any_host_by_roles", "map_hosts_by_roles"):
        getattr(cluster, method).return_value.result.return_value = None
    return cluster


class TestShardedAlterRouting(unittest.TestCase):
    def _exec_with_cloud(self, node_roles: list[NodeRole], cluster: mock.MagicMock) -> None:
        with (
            mock.patch("posthog.clickhouse.client.migration_tools.settings.E2E_TESTING", False),
            mock.patch("posthog.clickhouse.client.migration_tools.settings.DEBUG", False),
            mock.patch("posthog.clickhouse.client.migration_tools.settings.CLOUD_DEPLOYMENT", "US"),
            mock.patch(
                "posthog.clickhouse.client.migration_tools.get_migrations_cluster",
                return_value=cluster,
            ),
        ):
            operation = run_sql_with_exceptions(
                sql="ALTER TABLE sharded_x ADD COLUMN y String",
                node_roles=node_roles,
                sharded=True,
                is_alter_on_replicated_table=True,
            )
            operation._func(None)

    def test_data_role_uses_map_one_host_per_shard(self):
        cluster = _build_cluster_mock()
        self._exec_with_cloud([NodeRole.DATA], cluster)
        cluster.map_one_host_per_shard.assert_called_once()
        cluster.any_host_by_roles.assert_not_called()

    @parameterized.expand([(role.name, role) for role in sorted(SINGLE_SHARD_DATA_NODE_ROLES, key=lambda r: r.name)])
    def test_satellite_role_uses_any_host_by_roles(self, _name: str, role: NodeRole):
        cluster = _build_cluster_mock()
        self._exec_with_cloud([role], cluster)
        cluster.any_host_by_roles.assert_called_once()
        _args, kwargs = cluster.any_host_by_roles.call_args
        self.assertEqual(kwargs["node_roles"], [role])
        cluster.map_one_host_per_shard.assert_not_called()

    def test_non_data_bearing_role_rejected(self):
        cluster = _build_cluster_mock()
        with self.assertRaises(AssertionError):
            self._exec_with_cloud([NodeRole.INGESTION_SMALL], cluster)
        cluster.any_host_by_roles.assert_not_called()
        cluster.map_one_host_per_shard.assert_not_called()

    def test_local_or_test_falls_through_to_per_shard(self):
        cluster = _build_cluster_mock()
        with (
            mock.patch("posthog.clickhouse.client.migration_tools.settings.DEBUG", True),
            mock.patch(
                "posthog.clickhouse.client.migration_tools.get_migrations_cluster",
                return_value=cluster,
            ),
        ):
            operation = run_sql_with_exceptions(
                sql="ALTER TABLE sharded_x ADD COLUMN y String",
                node_roles=[NodeRole.AUX],
                sharded=True,
                is_alter_on_replicated_table=True,
            )
            operation._func(None)
        cluster.map_one_host_per_shard.assert_called_once()
        cluster.any_host_by_roles.assert_not_called()

    def test_data_node_roles_membership(self):
        self.assertIn(NodeRole.DATA, DATA_NODE_ROLES)
        for role in SINGLE_SHARD_DATA_NODE_ROLES:
            self.assertIn(role, DATA_NODE_ROLES)
        self.assertNotIn(NodeRole.DATA, SINGLE_SHARD_DATA_NODE_ROLES)


def _cluster_with_unknown_role_host() -> ClickhouseCluster:
    bootstrap_client = mock.Mock()
    bootstrap_client.execute = mock.Mock(
        return_value=[
            ("data-host", "9000", "1", "1", "online", "data"),
            ("test-host", "9000", "1", "1", "online", "test"),
        ]
    )
    return ClickhouseCluster(bootstrap_client)


class TestAllRoleHostSelection(unittest.TestCase):
    @parameterized.expand(
        [
            ("alter_skips_unknown_role", "ALTER TABLE t ADD COLUMN IF NOT EXISTS c String", {"data-host"}),
            (
                "create_keeps_unknown_role",
                "CREATE TABLE IF NOT EXISTS t (c String) ENGINE = Log",
                {"data-host", "test-host"},
            ),
        ]
    )
    def test_all_role_hosts_in_cloud(self, _name: str, sql: str, expected: set[str]) -> None:
        cluster = _cluster_with_unknown_role_host()
        visited: set[str] = set()

        def fake_task(_self, host, fn):
            visited.add(host.connection_info.host)
            return lambda: None

        with (
            mock.patch("posthog.clickhouse.client.migration_tools._collapses_to_all_nodes", return_value=False),
            mock.patch("posthog.clickhouse.client.migration_tools.get_migrations_cluster", return_value=cluster),
            mock.patch.object(ClickhouseCluster, "_ClickhouseCluster__get_task_function", fake_task),
        ):
            run_sql_with_exceptions(sql, node_roles=[NodeRole.ALL])._func(None)

        self.assertEqual(visited, expected)


class TestSkipIfTableMissing(unittest.TestCase):
    @parameterized.expand([("table_missing", 0, 1), ("table_present", 1, 2)])
    def test_runs_query_only_when_table_exists(self, _name: str, table_count: int, expected_calls: int) -> None:
        client = mock.Mock()
        client.execute.return_value = [[table_count]]

        SkipIfTableMissing("t", Query("ALTER TABLE t ADD COLUMN IF NOT EXISTS c String"))(client)

        self.assertEqual(client.execute.call_count, expected_calls)
        if expected_calls == 2:
            self.assertEqual(client.execute.call_args.args[0], "ALTER TABLE t ADD COLUMN IF NOT EXISTS c String")
