from unittest.mock import MagicMock

import psycopg.errors

from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    add_table_to_publication,
    remove_table_from_publication,
)


def _mock_conn(execute_side_effect=None):
    """Create a mock psycopg connection with a context-manager cursor."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.commit = MagicMock()
    conn.rollback = MagicMock()

    if execute_side_effect is not None:
        cursor.execute.side_effect = execute_side_effect

    return conn, cursor


class TestAddTableToPublication:
    def test_add_table_success(self):
        conn, cursor = _mock_conn()

        add_table_to_publication(conn, pub_name="my_pub", schema="public", table="users")

        cursor.execute.assert_called_once()
        sql_str = str(cursor.execute.call_args[0][0])
        assert "ALTER PUBLICATION" in sql_str
        assert "ADD TABLE" in sql_str
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_add_table_duplicate_is_noop(self):
        conn, cursor = _mock_conn(execute_side_effect=psycopg.errors.DuplicateObject())

        add_table_to_publication(conn, pub_name="my_pub", schema="public", table="users")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


class TestRemoveTableFromPublication:
    def test_remove_table_success(self):
        conn, cursor = _mock_conn()

        remove_table_from_publication(conn, pub_name="my_pub", schema="public", table="users")

        cursor.execute.assert_called_once()
        sql_str = str(cursor.execute.call_args[0][0])
        assert "ALTER PUBLICATION" in sql_str
        assert "DROP TABLE" in sql_str
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_remove_table_missing_is_noop(self):
        conn, cursor = _mock_conn(execute_side_effect=psycopg.errors.UndefinedTable())

        remove_table_from_publication(conn, pub_name="my_pub", schema="public", table="users")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
