import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import InterfaceError, InternalError, OperationalError

import psycopg.errors
import temporalio.exceptions
from databricks.sql.exc import RequestError
from parameterized import parameterized
from temporalio.worker import ExecuteActivityInput

from posthog.dataclasses import frozen
from posthog.temporal.common.posthog_client import _PostHogClientActivityInboundInterceptor


def _wrapped_by_django(message: str, cause: Exception, error_cls: type[Exception] = OperationalError) -> Exception:
    error = error_cls(message)
    error.__cause__ = cause
    return error


def _databricks_request_error(original: Exception) -> RequestError:
    # The driver passes the original error as a positional arg and keeps only its str in the context.
    return RequestError("Error during request to server", {"original-exception": str(original)}, None, original)


def _raised_from(error: Exception, cause: BaseException) -> Exception:
    error.__cause__ = cause
    return error


@frozen
class _Input:
    team_id: int


async def _run_and_capture(error: Exception) -> MagicMock:
    next_interceptor = AsyncMock()
    next_interceptor.execute_activity.side_effect = error
    interceptor = _PostHogClientActivityInboundInterceptor(next_interceptor)

    mock_input = MagicMock(spec=ExecuteActivityInput)
    mock_input.args = [_Input(team_id=1)]
    mock_input.fn = _run_and_capture

    with (
        patch("posthog.temporal.common.posthog_client.api_key", "phc_test"),
        patch("posthog.temporal.common.posthog_client.activity.info", return_value=MagicMock()),
        patch("posthog.temporal.common.posthog_client.capture_exception") as mock_capture,
    ):
        with pytest.raises(type(error)):
            await interceptor.execute_activity(mock_input)
    return mock_capture


@pytest.mark.asyncio
class TestTransientDatabaseErrorReporting:
    @parameterized.expand(
        [
            ("pool_wait_timeout", OperationalError("query_wait_timeout")),
            ("connection_dropped", OperationalError("server closed the connection unexpectedly")),
            ("interface_error", InterfaceError("connection reset by peer")),
            (
                "server_shutdown_sqlstate",
                _wrapped_by_django(
                    "terminating connection due to administrator command",
                    psycopg.errors.AdminShutdown("terminating connection due to administrator command"),
                ),
            ),
            # psycopg classes read_only_sql_transaction (a primary briefly refusing writes mid
            # failover) under its own InternalError, not OperationalError — Django follows suit.
            (
                "read_only_transaction_failover",
                _wrapped_by_django(
                    "cannot execute SELECT FOR UPDATE in a read-only transaction",
                    psycopg.errors.ReadOnlySqlTransaction(
                        "cannot execute SELECT FOR UPDATE in a read-only transaction"
                    ),
                    error_cls=InternalError,
                ),
            ),
            # Code using a raw psycopg connection instead of Django's ORM (e.g. the
            # warehouse-sources postgres queue producer) raises psycopg's own exception classes
            # directly, never wrapped in Django's OperationalError/InterfaceError/InternalError.
            (
                "native_psycopg_pgbouncer_login_retry",
                psycopg.errors.ProtocolViolation(
                    "server login has been failing, cached error: connect failed (server_login_retry)"
                ),
            ),
        ]
    )
    async def test_transient_db_errors_are_not_reported(self, _name, error):
        # Temporal retries the activity, so a burst of pool timeouts must not mint an issue each.
        mock_capture = await _run_and_capture(error)
        mock_capture.assert_not_called()

    @parameterized.expand(
        [
            ("deadlock", OperationalError("deadlock detected")),
            # psycopg prefixes every failed connect with "connection failed:", so persistent
            # misconfiguration must not be swallowed as transient.
            (
                "bad_credentials",
                OperationalError(
                    'connection failed: connection to server at "127.0.0.1", port 6432 failed: '
                    'FATAL:  password authentication failed for user "posthog"'
                ),
            ),
        ]
    )
    async def test_other_database_errors_are_still_reported(self, _name, error):
        mock_capture = await _run_and_capture(error)
        mock_capture.assert_called_once()


@pytest.mark.asyncio
class TestWrappedCancellationReporting:
    @parameterized.expand(
        [
            ("databricks_request_error", _databricks_request_error(temporalio.exceptions.CancelledError("Cancelled"))),
            ("raised_from_cancellation", _raised_from(RuntimeError("driver failed"), asyncio.CancelledError())),
        ]
    )
    async def test_wrapped_cancellations_are_not_reported(self, _name, error):
        mock_capture = await _run_and_capture(error)
        mock_capture.assert_not_called()

    async def test_databricks_request_error_without_cancellation_is_still_reported(self):
        mock_capture = await _run_and_capture(_databricks_request_error(ConnectionResetError("connection reset")))
        mock_capture.assert_called_once()
