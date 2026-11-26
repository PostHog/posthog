"""Start a Support AI run that a teammate asked for on one ticket."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from django.conf import settings
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

# A run that started longer ago than this is treated as dead, so a stuck status cannot block the button forever.
STALE_RUN_AFTER = timedelta(minutes=30)


class ManualRerunRefused(Exception):
    """The run was not started. `error_type` is the machine-readable reason."""

    def __init__(self, error_type: str, detail: str, *, conflict: bool) -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail
        # True when the request was valid and the ticket's state is the reason.
        self.conflict = conflict


def manual_rerun_workflow_id(ticket_id: str, latest_activity: datetime) -> str:
    # The id names the ticket's state. A second request with no new message since the last run
    # gets the same id, and Temporal refuses it, so one state costs one run.
    return f"support-reply-{ticket_id}-m{int(latest_activity.timestamp())}"


def _run_in_progress(triage: dict, *, now: datetime) -> bool:
    if triage.get("status") != "in_progress":
        return False
    started_at = triage.get("started_at")
    if not isinstance(started_at, str):
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if started.tzinfo is None:
        return True
    return now - started < STALE_RUN_AFTER


def start_manual_rerun(ticket: Ticket, team: Team) -> str:
    """Start a run for `ticket` and return its workflow id. Raises ManualRerunRefused when it does not start."""
    # The coordinator module loads the Temporal workflows. Importing it here keeps them off the API import path.
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

    triage = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
    if _run_in_progress(triage, now=timezone.now()):
        raise ManualRerunRefused("ai_rerun_in_progress", "Support AI is already working on this ticket.", conflict=True)

    latest_comment_at = Comment.objects.filter(
        team_id=team.id, scope="conversations_ticket", item_id=str(ticket.id), deleted=False
    ).aggregate(latest=Max("created_at"))["latest"]
    workflow_id = manual_rerun_workflow_id(str(ticket.id), latest_comment_at or ticket.created_at)

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
        raise ManualRerunRefused(
            "ai_rerun_nothing_new",
            "Support AI already ran on this ticket and nothing was added since. Add a message or a note, then run it again.",
            conflict=True,
        ) from None
    except RPCError as error:
        raise ManualRerunRefused(
            "ai_rerun_failed", "Could not start Support AI. Try again in a minute.", conflict=False
        ) from error
    return workflow_id
