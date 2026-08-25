import pytest

from django.db import InterfaceError, InternalError, OperationalError

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
    ],
)
def test_is_transient_db_error_by_message(error: BaseException, expected: bool) -> None:
    assert is_transient_db_error(error) is expected


@pytest.mark.parametrize(
    "error_cls,sqlstate,expected",
    [
        (OperationalError, "57P03", True),  # cannot_connect_now (server starting up/shutting down)
        (OperationalError, "3D000", False),  # invalid_catalog_name — persistent misconfiguration
        (OperationalError, "08P01", False),  # protocol_violation — shared with genuine protocol bugs, so message-only
        # read_only_sql_transaction: a primary briefly refusing writes/locks mid-failover. psycopg
        # classes this under its own InternalError rather than OperationalError.
        (InternalError, "25006", True),
        (InternalError, "42601", False),  # syntax_error — a real bug, must keep reaching error tracking
    ],
)
def test_is_transient_db_error_by_sqlstate(error_cls: type[Exception], sqlstate: str, expected: bool) -> None:
    error = error_cls("some driver-specific message")
    error.__cause__ = _WithSqlstate(sqlstate)
    assert is_transient_db_error(error) is expected
