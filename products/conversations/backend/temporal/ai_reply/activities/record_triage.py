from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction

import structlog
from temporalio import activity

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import ph_background_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ai_reply.schemas import RecordTriageInput

logger = structlog.get_logger(__name__)

RUN_COMPLETED_EVENT = "support ai reply run completed"


def _merge_triage(input: RecordTriageInput) -> bool:
    """Merge the patch into the ticket's ai_triage JSON. Returns False when the ticket is gone."""
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(team_id=input.team_id, id=input.ticket_id).first()
        if ticket is None:
            return False
        patch = dict(input.patch)
        clear_clarification = bool(patch.pop("clear_clarification", False))
        current = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
        # Follow-up rounds still record in_progress at start. Keep awaiting_clarification so
        # persist can tell a human did not take the ticket, and a human reply can still cancel.
        if current.get("status") == "awaiting_clarification" and patch.get("status") == "in_progress":
            patch.pop("status")
        # Merge even if persist already cleared awaiting, so result and cost still land.
        merged = {**current, **patch}
        update_fields = ["ai_triage", "updated_at"]
        if clear_clarification and current.get("status") == "awaiting_clarification":
            # Reopen only tickets the AI itself parked in pending. A human may already
            # have moved status.
            if ticket.status == Status.PENDING:
                ticket.status = Status.OPEN
                update_fields.append("status")
            merged["status"] = "done"
        ticket.ai_triage = merged
        ticket.save(update_fields=update_fields)
    return True


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _capture_run_completed(input: RecordTriageInput) -> None:
    patch = input.patch
    cost = patch.get("cost")
    if not isinstance(cost, dict):
        cost = {}
    draft_task_run_ids = [str(run_id) for run_id in patch.get("draft_task_run_ids") or []]
    run_id = patch.get("run_id")
    try:
        team = Team.objects.get(id=input.team_id)
        ph_background_capture()(
            distinct_id=str(team.uuid),
            event=RUN_COMPLETED_EVENT,
            # A retried activity re-sends the same uuid and timestamp, so the events table merges the copies.
            uuid=str(uuid5(NAMESPACE_URL, f"{RUN_COMPLETED_EVENT}:{run_id}")) if run_id else None,
            timestamp=_parse_timestamp(patch.get("finished_at")),
            properties={
                "ticket_id": str(input.ticket_id),
                "workflow_id": patch.get("workflow_id"),
                "run_id": run_id,
                "ai_triage_result": patch.get("result"),
                "ai_triage_status": patch.get("status"),
                "ticket_type": patch.get("ticket_type"),
                "attempts": patch.get("attempts"),
                "ai_trace_id": patch.get("ai_trace_id"),
                "draft_task_run_ids": draft_task_run_ids,
                "draft_run_count": len(draft_task_run_ids),
                "started_at": patch.get("started_at"),
                "finished_at": patch.get("finished_at"),
                "llm_calls": cost.get("llm_calls"),
                "sandbox_seconds": cost.get("sandbox_seconds"),
            },
            groups=groups(team=team),
        )
    except Exception:
        logger.warning("support_reply_run_capture_failed", team_id=input.team_id, exc_info=True)


def _record_triage_sync(input: RecordTriageInput) -> None:
    # Only the workflow's terminal patch carries finished_at.
    if _merge_triage(input) and "finished_at" in input.patch:
        _capture_run_completed(input)


@activity.defn(name="support-record-triage")
@close_db_connections
async def support_record_triage_activity(input: RecordTriageInput) -> None:
    """Merge triage/outcome metadata into the ticket's ai_triage JSON field."""
    await database_sync_to_async(_record_triage_sync, thread_sensitive=False)(input)
