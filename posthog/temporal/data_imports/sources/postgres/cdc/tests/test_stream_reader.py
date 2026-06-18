import pytest
from unittest import mock
from unittest.mock import patch

import psycopg

from posthog.temporal.data_imports.sources.postgres.cdc.stream_reader import PgCDCConnectionParams, PgCDCStreamReader


@pytest.fixture
def params():
    return PgCDCConnectionParams(
        host="localhost",
        port=5432,
        database="postgres",
        user="postgres",
        password="password",
        slot_name="posthog_slot",
        publication_name="posthog_pub",
    )


class TestPgCDCStreamReaderConnect:
    def test_connect_retries_transient_dropped_connection(self, params):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The exact transient drop surfaced in production when the SSH tunnel /
                # pooler closes the first connection before it is established.
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "posthog.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            reader.connect()

        assert reader._conn is good_conn
        assert connect.call_count == 2

    def test_connect_does_not_retry_permanent_error(self, params):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "posthog.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            with pytest.raises(psycopg.OperationalError):
                reader.connect()

        assert connect.call_count == 1


class TestPgCDCStreamReaderConfirmPosition:
    def test_confirm_position_retries_transient_dropped_connection(self, params):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The short-lived slot-advance connection reaches the source through the
                # same tunnel / pooler as the initial connect, so it can hit the same
                # transient drop while advancing the replication slot after a run.
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "posthog.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            reader.confirm_position("0/1234ABCD")

        assert connect.call_count == 2
        good_conn.commit.assert_called_once()
        good_conn.close.assert_called_once()

    def test_confirm_position_does_not_retry_permanent_error(self, params):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "posthog.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("posthog.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            with pytest.raises(psycopg.OperationalError):
                reader.confirm_position("0/1234ABCD")

        assert connect.call_count == 1
