import unittest
from unittest.mock import patch

from posthog.clickhouse.client.connection import NodeRole
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

    @patch("posthog.clickhouse.client.migration_tools.settings")
    def test_explicit_node_roles_respected_in_debug_mode(self, mock_settings):
        """Explicit node_roles should not be overridden to ALL in debug mode."""
        mock_settings.DEBUG = True
        mock_settings.E2E_TESTING = False
        mock_settings.CLOUD_DEPLOYMENT = ""

        operation = run_sql_with_exceptions(
            sql="ALTER TABLE test ADD COLUMN x String",
            node_roles=[NodeRole.DATA],
        )

        self.assertEqual(operation._node_roles, [NodeRole.DATA])

    @patch("posthog.clickhouse.client.migration_tools.settings")
    def test_none_node_roles_defaults_to_all_in_debug_mode(self, mock_settings):
        """When node_roles is None, debug mode should still override to ALL."""
        mock_settings.DEBUG = True
        mock_settings.E2E_TESTING = False
        mock_settings.CLOUD_DEPLOYMENT = ""

        operation = run_sql_with_exceptions(
            sql="ALTER TABLE test ADD COLUMN x String",
            node_roles=None,
        )

        # node_roles=None -> default [NodeRole.DATA] -> override to [NodeRole.ALL]
        # original_node_roles captured before override = [NodeRole.DATA]
        self.assertEqual(operation._node_roles, [NodeRole.DATA])

    @patch("posthog.clickhouse.client.migration_tools.settings")
    def test_explicit_node_roles_in_cloud_mode(self, mock_settings):
        """In cloud mode with no debug, None node_roles keeps default DATA."""
        mock_settings.DEBUG = False
        mock_settings.E2E_TESTING = False
        mock_settings.CLOUD_DEPLOYMENT = "US"

        operation = run_sql_with_exceptions(
            sql="ALTER TABLE test ADD COLUMN x String",
            node_roles=None,
        )

        self.assertEqual(operation._node_roles, [NodeRole.DATA])
