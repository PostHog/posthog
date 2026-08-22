"""`before_send` hook that drops transient database connection and DNS errors from autocapture.

`posthog/apps.py` turns on `posthoganalytics.enable_exception_autocapture`, so every non-DEBUG
deployment ships its uncaught Django exceptions to PostHog Cloud. A self-hosted stack that boots
before its Postgres hostname resolves (a common docker-compose race) raises a burst of connection
and DNS errors that reach our error tracking and help nobody. These conditions clear on their own,
so they are noise, not defects — the Temporal interceptor drops the same class of error via
`posthog.temporal.common.db_errors.is_transient_db_error`.

The `before_send` hook runs on the built event dict, not the exception object, so this matches on
the `type` and `value` strings in `$exception_list` instead of the exception class.
"""

from typing import Any, Optional

# psycopg cannot resolve the database hostname yet — the docker-compose boot race. Unambiguous,
# so matched regardless of exception type.
_DNS_FAILURE_MARKERS = (
    "could not translate host name",
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname provided",
)

# Transient Postgres/pgbouncer conditions that clear on their own. Mirrors the marker set in
# posthog.temporal.common.db_errors — kept as a local copy because that module classifies live
# exception objects, while this hook only sees serialized type/value strings. Matched only when the
# exception type is a connection error, so a genuine defect quoting one of these strings still
# reaches error tracking.
_TRANSIENT_CONNECTION_MARKERS = (
    "connection refused",
    "could not connect to server",
    "server closed the connection unexpectedly",
    "connection reset by peer",
    "the database system is starting up",
    "the database system is shutting down",
    "server conn crashed",
    "server login has been failing, cached error",
    "query_wait_timeout",
    "pooler is shutting down",
)

# Exception class names that carry a transient connection failure. Bare names, since the event
# stores the class `__name__` (e.g. django.db.utils.OperationalError serializes as "OperationalError").
_CONNECTION_ERROR_TYPES = frozenset({"OperationalError", "InterfaceError"})


def _is_transient_connection_event(exception_entry: dict[str, Any]) -> bool:
    value = str(exception_entry.get("value") or "").lower()
    if any(marker in value for marker in _DNS_FAILURE_MARKERS):
        return True
    if exception_entry.get("type") in _CONNECTION_ERROR_TYPES:
        return any(marker in value for marker in _TRANSIENT_CONNECTION_MARKERS)
    return False


def drop_transient_connection_errors(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """SDK `before_send` hook: drop `$exception` events for transient DB connection or DNS failures.

    Returns `None` to drop the event, or the event unchanged otherwise. Never raises — the SDK
    treats a raising hook as a drop, but a defect here must not silently swallow real exceptions.
    """
    try:
        if event.get("event") != "$exception":
            return event
        exception_list = event.get("properties", {}).get("$exception_list") or []
        if any(_is_transient_connection_event(entry) for entry in exception_list if isinstance(entry, dict)):
            return None
    except Exception:
        return event
    return event
