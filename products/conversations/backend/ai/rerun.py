"""Start a Support AI run that a teammate asked for on one ticket."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.temporal.common.client import sync_connect

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.constants import TRIGGER_MANUAL

# A run older than this is treated as dead, so a stuck status cannot block new runs forever.
STALE_RUN_AFTER = timedelta(minutes=30)
# A request's claim on the ticket. It only covers the seconds before the workflow records `in_progress`.
CLAIM_KEY = "manual_run_claimed_at"
CLAIM_HOLDS_FOR = timedelta(minutes=2)


class ManualRerunRefused(Exception):
    """The run was not started. `error_type` is the machine-readable reason."""

    def __init__(self, error_type: str, detail: str, *, conflict: bool) -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        self.conflict = conflict


def manual_rerun_workflow_id(ticket_id: str, latest_activity: datetime) -> str:
    # The id names the ticket's state, so Temporal refuses a second run when no new message arrived.
    return f"support-reply-{ticket_id}-m{int(latest_activity.timestamp())}"


def _is_recent(value: object, *, now: datetime, within: timedelta) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and now - parsed < within


def _run_in_progress(triage: dict, *, now: datetime) -> bool:
    if _is_recent(triage.get(CLAIM_KEY), now=now, within=CLAIM_HOLDS_FOR):
        return True
    if triage.get("status") != "in_progress":
        return False
    started_at = triage.get("started_at")
    return not isinstance(started_at, str) or _is_recent(started_at, now=now, within=STALE_RUN_AFTER)


def _claim(ticket_id: str, team_id: int) -> str:
    """Mark the ticket as claimed by this request, or refuse when a run is already under way."""
    now = timezone.now()
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().filter(team_id=team_id, id=ticket_id).first()
        triage = dict(locked.ai_triage) if locked and isinstance(locked.ai_triage, dict) else {}
        if locked is None or _run_in_progress(triage, now=now):
            raise ManualRerunRefused(
                "ai_rerun_in_progress", "Support AI is already working on this ticket.", conflict=True
            )
        claim = now.isoformat()
        locked.ai_triage = {**triage, CLAIM_KEY: claim}
        locked.save(update_fields=["ai_triage"])
    return claim


def _release_claim(ticket_id: str, team_id: int, claim: str) -> None:
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().filter(team_id=team_id, id=ticket_id).first()
        triage = dict(locked.ai_triage) if locked and isinstance(locked.ai_triage, dict) else {}
        if locked is None or triage.get(CLAIM_KEY) != claim:
            return
        del triage[CLAIM_KEY]
        locked.ai_triage = triage
        locked.save(update_fields=["ai_triage"])


def start_manual_rerun(ticket: Ticket, team: Team) -> str:
    """Start a run for `ticket` and return its workflow id. Raises ManualRerunRefused when it does not start."""
    # Imported here to keep the Temporal workflows off the API import path.
    from products.conversations.backend.temporal.coordinator import _is_master_flag_enabled  # noqa: PLC0415
    from products.conversations.backend.temporal.pipeline import (  # noqa: PLC0415
        SupportReplyInput,
        SupportReplyWorkflow,
    )

    conversations_settings = team.conversations_settings or {}
    if (
        not conversations_settings.get("ai_suggestions_enabled", False)
        or not team.organization.is_ai_data_processing_approved
        or not _is_master_flag_enabled(team)
    ):
        raise ManualRerunRefused(
            "ai_rerun_unavailable", "Support AI is not turned on for this project.", conflict=False
        )

    # A note that a run wrote must not count as new input, or each run would allow the next one.
    latest_message_at = (
        Comment.objects.filter(team_id=team.id, scope="conversations_ticket", item_id=str(ticket.id), deleted=False)
        .exclude(item_context__author_type="AI")
        .exclude(item_context__is_private=True)
        .aggregate(latest=Max("created_at"))["latest"]
    )
    workflow_id = manual_rerun_workflow_id(str(ticket.id), latest_message_at or ticket.created_at)

    claim = _claim(str(ticket.id), team.id)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SupportReplyWorkflow.run,
                SupportReplyInput(team_id=team.id, ticket_id=str(ticket.id), trigger=TRIGGER_MANUAL),
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        )
    except WorkflowAlreadyStartedError:
        _release_claim(str(ticket.id), team.id, claim)
        raise ManualRerunRefused(
            "ai_rerun_nothing_new",
            "Support AI already ran on this ticket and no new message has arrived since.",
            conflict=True,
        ) from None
    except RPCError as error:
        _release_claim(str(ticket.id), team.id, claim)
        raise ManualRerunRefused(
            "ai_rerun_failed", "Could not start Support AI. Try again in a minute.", conflict=False
        ) from error
    return workflow_id
