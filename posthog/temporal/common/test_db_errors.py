import pytest

from django.db import InterfaceError, OperationalError

import psycopg

from posthog.temporal.common.db_errors import is_transient_db_error


class _WithSqlstate(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    "error,expected",
    [
        (ValueError("query_wait_timeout"), False),
        (OperationalError("query_wait_timeout"), True),
        (OperationalError("server closed the connection unexpectedly"), True),
        (InterfaceError("connection reset by peer"), True),
        (OperationalError("the database system is starting up"), True),
        (OperationalError("the database system is shutting down"), True),
        (
            OperationalError("server login has been failing, cached error: server conn crashed? (server_login_retry)"),
            True,
        ),
        # The dead-socket message on its own, without pgbouncer's cached-login wrapper — the case
        # the marker above doesn't cover.
        (OperationalError("server conn crashed?"), True),
        (
            OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 6543 failed: '
                "FATAL:  pooler is shutting down"
            ),
            True,
        ),
        (OperationalError("connection failed: FATAL: password authentication failed for user"), False),
        (OperationalError("no such database"), False),
        # duckgres out of capacity on session create — raised as a raw psycopg error, not a
        # Django-wrapped one, so it exercises the widened class check too.
        (
            psycopg.OperationalError("ResourceExhausted: create session: initialize ducklake session metadata"),
            True,
        ),
        # A raw psycopg misconfiguration error must still surface.
        (psycopg.OperationalError("connection failed: FATAL: password authentication failed for user"), False),
        # duckgres backend killed mid-query: the server shutdown raises a raw psycopg error that
        # carries the transient 57P SQLSTATE on itself (not on a Django __cause__), with a message
        # that is not in the markers. It must still classify as transient via SQLSTATE.
        (psycopg.errors.AdminShutdown("terminating connection due to administrator command"), True),
    ],
)
def test_is_transient_db_error_by_message(error: BaseException, expected: bool) -> None:
    assert is_transient_db_error(error) is expected


@pytest.mark.parametrize(
    "sqlstate,expected",
    [
        ("57P03", True),  # cannot_connect_now (server starting up/shutting down)
        ("3D000", False),  # invalid_catalog_name — persistent misconfiguration
        ("08P01", False),  # protocol_violation — shared with genuine protocol bugs, so message-only
    ],
)
def test_is_transient_db_error_by_sqlstate(sqlstate: str, expected: bool) -> None:
    error = OperationalError("some driver-specific message")
    error.__cause__ = _WithSqlstate(sqlstate)
    assert is_transient_db_error(error) is expected
