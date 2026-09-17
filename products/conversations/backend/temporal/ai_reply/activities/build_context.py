from __future__ import annotations

from temporalio import activity

from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.business_knowledge.backend.logic import get_always_on_context
from products.conversations.backend.ai.suggest import _build_ticket_context
from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.constants import (
    MAX_TICKET_CONTEXT_CHARS,
    PUBLISHABLE_TICKET_TYPES,
)
from products.conversations.backend.temporal.ai_reply.publish import channel_allows_bot_reply
from products.conversations.backend.temporal.ai_reply.schemas import BuildContextOutput, SupportReplyInput


@activity.defn
@close_db_connections
async def support_build_context_activity(input: SupportReplyInput) -> BuildContextOutput:
    """Build the full ticket context string reusing the existing suggest.py helper."""
    async with Heartbeater():
        return await database_sync_to_async(_build_context_sync, thread_sensitive=False)(
            input.team_id, input.ticket_id, input.clarification_round
        )


def _build_context_sync(team_id: int, ticket_id: str, clarification_round: int = 0) -> BuildContextOutput:
    ticket = Ticket.objects.select_related("team").get(id=ticket_id, team_id=team_id)
    team = ticket.team
    comments = list(
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
        )
        .exclude(item_context__is_private=True)
        .order_by("created_at")
    )
    context = _build_ticket_context(ticket, comments, team)[:MAX_TICKET_CONTEXT_CHARS]
    title = getattr(ticket, "title", "") or f"Ticket {ticket_id}"

    always_on_chunks = get_always_on_context(team_id)
    always_on_text = "\n\n".join(c.content for c in always_on_chunks) if always_on_chunks else ""

    settings_dict = team.conversations_settings or {}
    diagnostics_allowed = bool(settings_dict.get("ai_diagnostics_enabled", False))

    auto_publish_ticket_types = [
        tt for tt in PUBLISHABLE_TICKET_TYPES if channel_allows_bot_reply(ticket=ticket, ticket_type=tt)
    ]

    triage = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
    prior_ticket_type = triage.get("ticket_type") if isinstance(triage.get("ticket_type"), str) else ""
    prior_needs_diagnostics = bool(triage.get("needs_diagnostics"))
    followup_cancelled = clarification_round >= 1 and triage.get("status") != "awaiting_clarification"

    return BuildContextOutput(
        ticket_context=context,
        ticket_title=title,
        always_on_context=always_on_text,
        diagnostics_allowed=diagnostics_allowed,
        auto_publish_ticket_types=auto_publish_ticket_types,
        prior_ticket_type=prior_ticket_type or "",
        prior_needs_diagnostics=prior_needs_diagnostics,
        followup_cancelled=followup_cancelled,
    )
