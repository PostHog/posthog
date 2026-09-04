from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.apply_persons_migrations import TRACKING_TABLE, _apply_migration


class TestApplyMigrationTransactionRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_transaction_marker", "-- no-transaction\nDROP INDEX CONCURRENTLY IF EXISTS foo;\n", False),
            ("regular_file", "CREATE TABLE foo (id int);\n", True),
        ]
    )
    def test_wraps_only_regular_files_in_a_transaction(self, _name, sql_content, expects_transaction):
        conn = MagicMock()
        cursor = MagicMock()

        _apply_migration(conn, cursor, sql_content, "x.sql")

        if expects_transaction:
            conn.transaction.assert_called_once()
        else:
            conn.transaction.assert_not_called()

        cursor.execute.assert_any_call(sql_content)
        cursor.execute.assert_any_call(f"INSERT INTO {TRACKING_TABLE} (filename) VALUES (%s)", ["x.sql"])
