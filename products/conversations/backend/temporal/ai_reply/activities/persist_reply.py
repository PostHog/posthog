from __future__ import annotations

from django.db import transaction

from temporalio import activity

from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.constants import PUBLISHABLE_TICKET_TYPES
from products.conversations.backend.temporal.ai_reply.gate import format_findings_comment
from products.conversations.backend.temporal.ai_reply.schemas import PersistReplyInput, coerce_dataclass


@activity.defn
@close_db_connections
async def support_persist_reply_activity(input: PersistReplyInput) -> None:
    """Persist the validated reply as an AI comment on the ticket (private note or bot reply per settings)."""
    async with Heartbeater():
        await database_sync_to_async(_persist_reply_sync, thread_sensitive=False)(input)


def _persist_reply_sync(input: PersistReplyInput) -> None:
    input = coerce_dataclass(PersistReplyInput, input)
    persist_as = input.persist_as
    is_private = True
    # Only how_to replies may be published. diagnostic/account_billing draw on project data and
    # must stay private regardless of the team's ai_reply_modes — guards against stale settings
    # since validation now rejects bot_reply for those types. Controlled by team-level opt-in.
    if persist_as != "findings" and input.allow_bot_reply and input.ticket_type in PUBLISHABLE_TICKET_TYPES:
        ticket = Ticket.objects.select_related("team").filter(team_id=input.team_id, id=input.ticket_id).first()
        if ticket:
            settings_dict = ticket.team.conversations_settings or {}
            modes = settings_dict.get("ai_reply_modes") or {}
            channel_modes = modes.get(ticket.channel_source) or {}
            mode = channel_modes.get(input.ticket_type, "private_note")
            if mode == "bot_reply":
                is_private = False

    content = input.reply
    item_context: dict[str, object] = {
        "author_type": "AI",
        "is_private": is_private,
        "citations": input.citations,
        "confidence": input.confidence,
        "persist_as": persist_as,
    }
    if persist_as == "findings":
        content = format_findings_comment(
            investigation_summary=input.investigation_summary,
            unknowns=input.unknowns,
            clarifying_questions=input.clarifying_questions,
            findings_reason=input.findings_reason,
            citations=input.citations,
        )
        item_context["investigation_summary"] = input.investigation_summary
        item_context["unknowns"] = input.unknowns
        item_context["clarifying_questions"] = input.clarifying_questions
        item_context["findings_reason"] = input.findings_reason

    # ATOMIC_REQUESTS is off, so wrap the comment insert with the email-outbox write.
    with transaction.atomic():
        Comment.objects.create(
            team_id=input.team_id,
            scope="conversations_ticket",
            item_id=input.ticket_id,
            content=content,
            item_context=item_context,
        )
