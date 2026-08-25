"""Detect a Postgres read-only transaction error on PostHog's own database.

During an Aurora writer failover or maintenance promotion the writer briefly serves a
read-only session, so every write raises SQLSTATE 25006 (``read_only_sql_transaction``).
psycopg raises ``psycopg.errors.ReadOnlySqlTransaction``, which Django wraps as
``django.db.InternalError`` and chains the psycopg error on ``__cause__``. Match on the
SQLSTATE so both the raw and the wrapped forms are detected.
"""

import structlog

logger = structlog.get_logger(__name__)

READ_ONLY_SQLSTATE = "25006"


def is_read_only_transaction_error(exc: BaseException | None) -> bool:
    """Return True when ``exc`` or a cause in its chain is a read-only transaction error."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "sqlstate", None) == READ_ONLY_SQLSTATE:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def is_read_only_transaction_event(event: dict) -> bool:
    """Return True when a captured ``$exception`` event describes a read-only transaction error.

    Exception autocapture passes ``before_send`` the wire event, not the exception object. The SDK
    walks the exception chain into ``$exception_list``, so a Django-wrapped error carries both the
    ``InternalError`` wrapper and the chained psycopg ``ReadOnlySqlTransaction`` as its own entry.
    Match on that type alone — matching the message text would also drop unrelated exceptions that
    merely mention a read-only transaction.
    """
    if event.get("event") != "$exception":
        return False
    for entry in (event.get("properties") or {}).get("$exception_list") or []:
        if entry.get("type") == "ReadOnlySqlTransaction":
            return True
    return False


def drop_read_only_transaction_exceptions(event: dict) -> dict | None:
    """``before_send`` hook that drops autocaptured read-only transaction exceptions.

    A brief writer failover fails every in-flight write at once, so without this each failover
    mints a fresh batch of error tracking issues that bury real regressions during the window
    when triage matters most. The condition is transient infrastructure state, not a code
    defect, so drop the event and leave a log line for the record.
    """
    if is_read_only_transaction_event(event):
        logger.warning("dropped_read_only_transaction_exception")
        return None
    return event
