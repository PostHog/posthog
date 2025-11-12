import unittest

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


class TestAlterReplicatedValidation(unittest.TestCase):
    def test_metadata_attached_to_operations(self):
        """Test that run_sql_with_exceptions attaches metadata correctly."""
        sql = "ALTER TABLE test_table ADD COLUMN test_col String"
        node_roles = [NodeRole.DATA, NodeRole.COORDINATOR]

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
