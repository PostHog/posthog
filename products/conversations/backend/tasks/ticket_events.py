from http import HTTPStatus
from typing import Any, cast

import structlog
from celery import shared_task

from posthog.api.capture import CaptureInternalError, CaptureInternalResult
from posthog.exceptions_capture import capture_exception

from products.conversations.backend.events import capture_ticket_tag_added

logger = structlog.get_logger(__name__)

RETRYABLE_CLIENT_ERRORS = frozenset({HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS})


def _fails_on_every_attempt(result: CaptureInternalResult) -> bool:
    if result.dropped:
        return True
    return 400 <= result.status_code < 500 and result.status_code not in RETRYABLE_CLIENT_ERRORS


@shared_task(
    name="products.conversations.backend.tasks.emit_ticket_tag_added",
    ignore_result=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def emit_ticket_tag_added(event: dict[str, Any], event_uuid: str, timestamp: str) -> None:
    """Capture one `$conversation_ticket_tag_added` that the tag receiver built.

    A workflow can trigger on this event, and a tag that is added again emits nothing, so a
    capture that can succeed later retries with backoff, and a worker that dies mid-task hands
    the task back to the queue. Every attempt sends the same event, uuid, and timestamp.
    """
    task = cast(Any, emit_ticket_tag_added)
    result = capture_ticket_tag_added(event, event_uuid=event_uuid, timestamp=timestamp)
    try:
        result.raise_for_status()
    except CaptureInternalError as e:
        ticket_id = event["properties"]["ticket_id"]
        if e.is_billing_limit_exceeded:
            logger.info("conversations_tag_added_event_billing_limited", ticket_id=ticket_id)
            return
        if _fails_on_every_attempt(result) or task.request.retries >= task.max_retries:
            capture_exception(e, {"ticket_id": ticket_id, "capture_verdicts": result.verdict_summary()})
            return
        raise task.retry(exc=e, countdown=60 * 2**task.request.retries)
