from collections.abc import Callable
from typing import Any

from django.core.cache import cache
from django.db import InterfaceError, OperationalError, connections
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.api.github_webhooks.metrics import observe_github_webhook_handler
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)
GithubWebhookHandler = Callable[[HttpRequest, str, dict[str, Any], str], HttpResponse | None]

GITHUB_WEBHOOK_DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60

# A pooler or Postgres disruption closes the connection under a running handler. Django keeps the
# dead connection for the rest of the request, so every query that follows on it fails too.
_CONNECTION_ERRORS = (OperationalError, InterfaceError)


def _is_duplicate_github_webhook_delivery(handler_name: str, delivery_id: str) -> bool:
    """Redis-backed per-handler delivery dedup, fail-open when the cache backend errors.

    Keyed per handler, not just per delivery id: one GitHub delivery legitimately fans
    out to multiple handlers (e.g. a pull_request delivery reaches both the tasks PR
    backstop and the Loops handler), so a delivery-wide key would starve every handler
    but the first. This sits alongside each consumer's own dedup (e.g. the conversations
    Celery task) rather than replacing it.
    """
    key = _github_webhook_delivery_key(handler_name, delivery_id)
    try:
        return not cache.add(key, True, timeout=GITHUB_WEBHOOK_DELIVERY_DEDUP_TTL_SECONDS)
    except Exception:
        logger.warning(
            "github_webhook_dedup_cache_failed", handler=handler_name, delivery_id=delivery_id, exc_info=True
        )
        return False


def _github_webhook_delivery_key(handler_name: str, delivery_id: str) -> str:
    return f"github_webhook_delivery:{handler_name}:{delivery_id}"


def _release_github_webhook_delivery(handler_name: str, delivery_id: str) -> None:
    """Drop the dedup mark after a handler failed, so GitHub's redelivery of the same
    GUID gets processed instead of silently skipped (the mark is set before the handler
    runs, so a failure would otherwise burn the delivery for 24h)."""
    try:
        cache.delete(_github_webhook_delivery_key(handler_name, delivery_id))
    except Exception:
        logger.warning(
            "github_webhook_dedup_release_failed", handler=handler_name, delivery_id=delivery_id, exc_info=True
        )


def _close_dead_connections() -> bool:
    """Close every database connection the error left unusable, and report if one was closed.

    `close_if_unusable_or_obsolete` keeps a connection that still answers, so a statement timeout
    or a deadlock closes nothing and the caller learns the connection is healthy. It skips a
    connection inside an atomic block, the same guard `close_stale_db_connections` carries, so a
    test transaction is not closed under the code that owns it.
    """
    closed = False
    for db_connection in connections.all(initialized_only=True):
        if db_connection.in_atomic_block:
            continue
        db_connection.close_if_unusable_or_obsolete()
        closed = closed or db_connection.connection is None
    return closed


def _run_handler(
    handler: GithubWebhookHandler,
    request: HttpRequest,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str,
    handler_name: str,
) -> HttpResponse | None:
    """Run one handler, and run it a second time if a database connection dropped under it.

    The second run opens a fresh connection. A retry only helps when a connection died, so an
    OperationalError that left every connection healthy (a statement timeout, a deadlock) reaches
    the caller instead, and the handler does not repeat its slow query on the request thread.
    Handlers key their side effects on the delivery id (the Loops fire key, the conversations
    Celery dedup), so the second run repeats no work that the first one completed.
    """
    try:
        return handler(request, event_type, payload, delivery_id)
    except _CONNECTION_ERRORS:
        if not _close_dead_connections():
            raise
        logger.warning(
            "github_webhook_handler_connection_retry",
            event_type=event_type,
            delivery_id=delivery_id,
            handler=handler_name,
            exc_info=True,
        )
        observe_github_webhook_handler(handler=handler_name, outcome="connection_retry")
        return handler(request, event_type, payload, delivery_id)


def dispatch_github_event(
    request: HttpRequest,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str,
    handlers: list[tuple[str, GithubWebhookHandler]],
) -> HttpResponse:
    logger.info(
        "github_webhook_dispatch",
        event_type=event_type,
        delivery_id=delivery_id,
        handlers_matched=[name for name, _ in handlers],
    )

    response: HttpResponse | None = None
    failed = False
    for name, handler in handlers:
        if delivery_id and _is_duplicate_github_webhook_delivery(name, delivery_id):
            logger.info("github_webhook_handler_deduped", event_type=event_type, delivery_id=delivery_id, handler=name)
            continue

        try:
            handler_response = _run_handler(handler, request, event_type, payload, delivery_id, name)
        except Exception as e:
            logger.exception(
                "github_webhook_handler_failed", event_type=event_type, delivery_id=delivery_id, handler=name
            )
            capture_exception(e)
            observe_github_webhook_handler(handler=name, outcome="failed")
            failed = True
            if delivery_id:
                _release_github_webhook_delivery(name, delivery_id)
            continue

        observe_github_webhook_handler(handler=name, outcome="ok")
        if response is None and handler_response is not None:
            response = handler_response

    if failed:
        # Answer with a failure status so GitHub marks the delivery failed and it stays available
        # for redelivery. A 200 tells GitHub the delivery is done, which loses the failed handler's
        # work with no record that a consumer never ran. The dedup mark of each failed handler is
        # released above, so a redelivery runs only the handlers that failed.
        return HttpResponse(status=500)

    return response if response is not None else HttpResponse(status=200)
