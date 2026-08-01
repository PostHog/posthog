from django.db import InterfaceError, OperationalError

from posthog.db_backends.failopen.base import CircuitOpenError

# Substrings identifying transient Postgres connection failures that callers should retry.
# PgBouncer's `query_wait_timeout` kills queries waiting too long for a backend connection,
# and a primary restart, failover, or shutdown surfaces as a dropped/reset/refused connection.
# All of these are retryable rather than permanent, so map them to a 503 instead of letting
# them escape as an unhandled 500.
TRANSIENT_DB_ERROR_MARKERS = (
    "query_wait_timeout",
    "server closed the connection unexpectedly",
    "connection failed",
    "connection already closed",
    "the database system is shutting down",
    "the database system is in recovery mode",
)


def is_transient_db_error(error: Exception) -> bool:
    # The circuit breaker already decided the target is down; no message to match against.
    if isinstance(error, CircuitOpenError):
        return True
    if not isinstance(error, OperationalError | InterfaceError):
        return False
    message = str(error)
    return any(marker in message for marker in TRANSIENT_DB_ERROR_MARKERS)
