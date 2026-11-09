from http import HTTPStatus
from typing import Any, cast

import structlog
from celery import shared_task

from posthog.api.capture import CaptureInternalError, CaptureInternalResult
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit

from products.conversations.backend.events import capture_ticket_tag_added
from products.conversations.backend.models.ticket import Ticket

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
)
@skip_team_scope_audit
def emit_ticket_tag_added(
    tagged_item_id: str,
    ticket_id: str,
    tag_id: str,
    tag_name: str,
    actor_id: int | None,
    workflow_id: str | None,
    timestamp: str,
) -> None:
    """Capture `$conversation_ticket_tag_added` for one new ticket tag.

    A workflow can trigger on this event, and a tag that is added again emits nothing, so a
    capture that can succeed later retries with backoff. The receiver fixes the tag's name,
    the timestamp, and the event's uuid (the tag row's id), so every attempt sends them unchanged.
    """
    task = cast(Any, emit_ticket_tag_added)
    # No team filter: a tag row holds the project's root team, but a ticket in a child
    # environment keeps the environment's team. The UUID alone identifies the ticket.
    ticket = Ticket.objects.select_related("team").filter(id=ticket_id).first()
    if ticket is None:
        return
    actor = User.objects.filter(id=actor_id).first() if actor_id is not None else None

    result = capture_ticket_tag_added(
        ticket,
        tag_id=tag_id,
        tag_name=tag_name,
        actor=actor,
        actor_type="user" if actor else "system",
        workflow_id=workflow_id,
        event_uuid=tagged_item_id,
        timestamp=timestamp,
    )
    try:
        result.raise_for_status()
    except CaptureInternalError as e:
        if e.is_billing_limit_exceeded:
            logger.info("conversations_tag_added_event_billing_limited", team_id=ticket.team_id)
            return
        if _fails_on_every_attempt(result) or task.request.retries >= task.max_retries:
            capture_exception(e, {"ticket_id": ticket_id, "capture_verdicts": result.verdict_summary()})
            return
        raise task.retry(exc=e, countdown=60 * 2**task.request.retries)
