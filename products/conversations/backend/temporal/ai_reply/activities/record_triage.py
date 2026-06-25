from __future__ import annotations

from typing import Any

from django.db import transaction

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.schemas import RecordTriageInput


@activity.defn(name="support-record-triage")
@close_db_connections
async def support_record_triage_activity(input: RecordTriageInput) -> None:
    """Merge triage/outcome metadata into the ticket's ai_triage JSON field."""
    await database_sync_to_async(_record_triage_sync, thread_sensitive=False)(
        input.team_id, input.ticket_id, input.patch
    )


def _record_triage_sync(team_id: int, ticket_id: str, patch: dict[str, Any]) -> None:
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(team_id=team_id, id=ticket_id).first()
        if ticket is None:
            return
        merged = {**(ticket.ai_triage or {}), **patch}
        ticket.ai_triage = merged
        ticket.save(update_fields=["ai_triage", "updated_at"])
