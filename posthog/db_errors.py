"""Helpers for classifying transient database failures.

PgBouncer (transaction-pooling on port 6543) kills queries that wait too long for a
backend connection when the pool is saturated, raising `query_wait_timeout`, and it
surfaces dropped/reset backend connections as connection failures. Both are transient
rather than permanent, so callers can map them to a retryable response (HTTP 503)
instead of letting them escape as an unhandled 500.
"""

# Substrings identifying transient database failures that clients should retry.
TRANSIENT_DB_ERROR_MARKERS = (
    "query_wait_timeout",
    "server closed the connection unexpectedly",
    "connection failed",
)


def is_transient_db_error(error: Exception) -> bool:
    message = str(error)
    return any(marker in message for marker in TRANSIENT_DB_ERROR_MARKERS)
