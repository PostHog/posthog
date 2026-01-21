"""
Test that logs cluster schema is properly created in test environment.
"""

from django.test import TestCase

from posthog.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_LOGS_CLUSTER_DATABASE


class TestLogsSchema(TestCase):
    def test_logs_tables_exist(self):
        """Verify that logs cluster tables are created in test environment."""
        # Check that logs31 table exists
        [[count]] = sync_execute(
            f"""
            SELECT count()
            FROM system.tables
            WHERE database = '{CLICKHOUSE_LOGS_CLUSTER_DATABASE}'
            AND name = 'logs31'
            """
        )
        self.assertEqual(count, 1, "logs31 table should exist")

        # Check that logs distributed table exists
        [[count]] = sync_execute(
            f"""
            SELECT count()
            FROM system.tables
            WHERE database = '{CLICKHOUSE_LOGS_CLUSTER_DATABASE}'
            AND name = 'logs'
            """
        )
        self.assertEqual(count, 1, "logs distributed table should exist")

        # Check that log_attributes table exists
        [[count]] = sync_execute(
            f"""
            SELECT count()
            FROM system.tables
            WHERE database = '{CLICKHOUSE_LOGS_CLUSTER_DATABASE}'
            AND name = 'log_attributes'
            """
        )
        self.assertEqual(count, 1, "log_attributes table should exist")

    def test_logs_schema_columns(self):
        """Verify that logs31 table has the expected columns."""
        columns = sync_execute(
            f"""
            SELECT name, type
            FROM system.columns
            WHERE database = '{CLICKHOUSE_LOGS_CLUSTER_DATABASE}'
            AND table = 'logs31'
            ORDER BY name
            """
        )

        column_names = {col[0] for col in columns}

        # Check for key columns
        expected_columns = {
            "uuid",
            "team_id",
            "timestamp",
            "observed_timestamp",
            "body",
            "severity_text",
            "severity_number",
            "service_name",
            "resource_attributes",
            "attributes_map_str",
            "attributes_map_float",
            "attributes_map_datetime",
        }

        self.assertTrue(
            expected_columns.issubset(column_names),
            f"Missing columns: {expected_columns - column_names}",
        )
