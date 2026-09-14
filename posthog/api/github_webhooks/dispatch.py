from collections.abc import Callable
from typing import Any

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)
GithubWebhookHandler = Callable[[HttpRequest, str, dict[str, Any], str], HttpResponse | None]

GITHUB_WEBHOOK_DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60


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
    for name, handler in handlers:
        if delivery_id and _is_duplicate_github_webhook_delivery(name, delivery_id):
            logger.info("github_webhook_handler_deduped", event_type=event_type, delivery_id=delivery_id, handler=name)
            continue

        try:
            handler_response = handler(request, event_type, payload, delivery_id)
        except Exception as e:
            logger.exception(
                "github_webhook_handler_failed", event_type=event_type, delivery_id=delivery_id, handler=name
            )
            capture_exception(e)
            if delivery_id:
                _release_github_webhook_delivery(name, delivery_id)
            continue

        if response is None and handler_response is not None:
            response = handler_response

    return response if response is not None else HttpResponse(status=200)
