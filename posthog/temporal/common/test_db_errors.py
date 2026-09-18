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
        # This worker (EMFILE) or its host (ENFILE) ran out of file descriptors while opening the
        # connect-path socket. psycopg stringifies the original OSError into the message and Django
        # wraps it again, so the rendered errno is the only evidence that reaches here.
        (OperationalError("[Errno 24] Too many open files"), True),
        (OperationalError("[Errno 23] Too many open files in system"), True),
        # An unresolvable host renders an errno the same way, and stays a persistent
        # misconfiguration that must keep reaching error tracking.
        (OperationalError("[Errno -2] Name or service not known"), False),
    ],
)
def test_is_transient_db_error_by_message(error: BaseException, expected: bool) -> None:
    assert is_transient_db_error(error) is expected


@pytest.mark.parametrize(
    "error_cls,sqlstate,expected",
    [
        (OperationalError, "57P03", True),  # cannot_connect_now (server starting up/shutting down)
        (OperationalError, "3D000", False),  # invalid_catalog_name — persistent misconfiguration
        (OperationalError, "08P01", False),  # protocol_violation — shared with genuine protocol bugs
        # read_only_sql_transaction: Django wraps psycopg's ReadOnlySqlTransaction as InternalError,
        # not OperationalError/InterfaceError — a primary/replica failover briefly rejects writes
        # with this exact SQLSTATE until promotion completes. Exercises the class-independent path.
        (InternalError, "25006", True),
        (InternalError, "42601", False),  # syntax_error — a real bug, must keep reaching error tracking
        # in_failed_sql_transaction shares class 25 with the code above but means a prior statement
        # in the same transaction already failed — a real defect, not a self-healing infra blip.
        # Guards against widening the match to the whole class-25 prefix instead of the exact code.
        (InternalError, "25P02", False),
    ],
)
def test_is_transient_db_error_by_sqlstate(error_cls: type[Exception], sqlstate: str, expected: bool) -> None:
    error = error_cls("some driver-specific message")
    error.__cause__ = _WithSqlstate(sqlstate)
    assert is_transient_db_error(error) is expected
