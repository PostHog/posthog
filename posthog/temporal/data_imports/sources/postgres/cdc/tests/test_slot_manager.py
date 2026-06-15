import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock
from unittest.mock import MagicMock

import psycopg.errors

from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    add_table_to_publication,
    cdc_pg_connection,
    remove_table_from_publication,
)
from posthog.temporal.data_imports.sources.postgres.postgres import SSL_REQUIRED_AFTER_DATE

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


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


class TestCdcPgConnectionSsl:
    @pytest.mark.parametrize(
        "is_new_source,ssh_tunnel_enabled,require_tls,expected_require_ssl",
        [
            (True, False, True, True),
            (True, True, True, True),
            (True, True, False, False),
            (False, False, True, False),
        ],
    )
    def test_honors_ssh_tunnel_tls_optout(self, is_new_source, ssh_tunnel_enabled, require_tls, expected_require_ssl):
        # CDC must derive `require_ssl` from the full config like the main pipeline path, so an
        # SSH-tunnel `require_tls` opt-out is honored. Otherwise SSL is forced on and a database
        # reached over an SSH tunnel that doesn't speak SSL fails with "server does not support SSL".
        from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

        config = PostgresSource().parse_config(
            {
                "host": "db.example.com",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "postgres",
                "schema": "public",
            }
        )
        if ssh_tunnel_enabled:
            config.ssh_tunnel = mock.MagicMock(enabled=True, require_tls=mock.MagicMock(enabled=require_tls))
        else:
            config.ssh_tunnel = None

        created_at = (
            SSL_REQUIRED_AFTER_DATE + dt.timedelta(days=1)
            if is_new_source
            else SSL_REQUIRED_AFTER_DATE - dt.timedelta(days=1)
        )
        source = SimpleNamespace(job_inputs={}, created_at=created_at)

        @contextmanager
        def fake_tunnel(self, config):
            yield ("127.0.0.1", 44549)

        with (
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.parse_config",
                return_value=config,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.with_ssh_tunnel",
                fake_tunnel,
            ),
            mock.patch("posthog.temporal.data_imports.sources.postgres.postgres._connect_to_postgres") as mock_connect,
        ):
            with cdc_pg_connection(cast(ExternalDataSource, source)):
                pass

        mock_connect.assert_called_once()
        assert mock_connect.call_args.kwargs["require_ssl"] is expected_require_ssl
