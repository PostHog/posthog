import unittest
from unittest import mock

from parameterized import parameterized

from posthog.clickhouse.client.connection import DATA_NODE_ROLES, SINGLE_SHARD_DATA_NODE_ROLES, NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


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
