from __future__ import annotations

from django.db import transaction

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ai_reply.schemas import RecordTriageInput


@activity.defn(name="support-record-triage")
@close_db_connections
async def support_record_triage_activity(input: RecordTriageInput) -> None:
    """Merge triage/outcome metadata into the ticket's ai_triage JSON field."""
    await database_sync_to_async(_record_triage_sync, thread_sensitive=False)(input)


def _record_triage_sync(input: RecordTriageInput) -> None:
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(team_id=input.team_id, id=input.ticket_id).first()
        if ticket is None:
            return
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
