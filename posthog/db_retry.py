from collections.abc import Callable
from typing import TypeVar

from django.db import connections

import structlog
from prometheus_client import Counter

from posthog.db_errors import is_dropped_connection_error

logger = structlog.get_logger(__name__)

DROPPED_CONNECTION_RETRY_COUNTER = Counter(
    "dropped_connection_retry_total",
    "Reads retried after their database connection dropped mid-query, by outcome.",
    labelnames=["operation", "outcome"],
)

_R = TypeVar("_R")


def retry_dropped_connection(operation: str, read: Callable[[], _R]) -> _R:
    """Run `read` a second time, on a fresh connection, when its connection dropped mid-query.

    `CONN_MAX_AGE` is 0, so every request opens its own connections, and a connection the server
    or the pooler drops mid-query fails the read outright — nothing on the request path retries
    it. One immediate retry covers that, because the condition is over as soon as a healthy
    connection is used.

    Only wrap work that is safe to run twice: the retry repeats the whole of `read`.

    `posthog.temporal.common.utils.retry_on_db_connection_drop` does the same for a Temporal
    activity, and retries on any connection failure because the activity's retry policy backs it
    off. A request has no such policy, so this one recovers a dead connection and nothing else.
    """
    try:
        return read()
    except Exception as error:
        if not is_dropped_connection_error(error) or not _discard_failed_connections():
            raise
        logger.warning("dropped_connection_retry", operation=operation, error=str(error))

    try:
        result = read()
    except Exception:
        DROPPED_CONNECTION_RETRY_COUNTER.labels(operation=operation, outcome="failed").inc()
        raise
    DROPPED_CONNECTION_RETRY_COUNTER.labels(operation=operation, outcome="recovered").inc()
    return result


def _discard_failed_connections() -> bool:
    """Close the connections a failed query left unusable, and report whether a retry can run.

    A retry cannot run inside an atomic block: Postgres discarded the transaction along with the
    connection, so every further query fails until the block unwinds.

    Closes outright rather than through `close_old_connections()`, which probes a connection we
    already know is dead, and which treats every connection as obsolete because `CONN_MAX_AGE`
    is 0 — so it would also drop the healthy ones this request is using.
    """
    failed = [connection for connection in connections.all(initialized_only=True) if connection.errors_occurred]
    if any(connection.in_atomic_block for connection in failed):
        return False
    for connection in failed:
        connection.close()
    return True
