from __future__ import annotations

from temporalio import activity

from posthog.models.comment import Comment
from posthog.models.team.team import Team
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
from products.conversations.backend.temporal.ai_reply.schemas import BuildContextOutput, SupportReplyInput


@activity.defn
@close_db_connections
async def support_build_context_activity(input: SupportReplyInput) -> BuildContextOutput:
    """Build the full ticket context string reusing the existing suggest.py helper."""
    async with Heartbeater():
        return await database_sync_to_async(_build_context_sync, thread_sensitive=False)(input.team_id, input.ticket_id)


def _build_context_sync(team_id: int, ticket_id: str) -> BuildContextOutput:
    team = Team.objects.get(id=team_id)
    ticket = Ticket.objects.get(id=ticket_id, team_id=team_id)
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

    # Which publishable types would auto-send on this ticket's channel (mirrors persist_reply's
    # publish gate: publishable type + channel mode == "bot_reply"). Used to keep data-read
    # scopes off any draft whose reply could reach the untrusted author unreviewed.
    channel_modes = (settings_dict.get("ai_reply_modes") or {}).get(ticket.channel_source) or {}
    auto_publish_ticket_types = [
        tt for tt in PUBLISHABLE_TICKET_TYPES if channel_modes.get(tt, "private_note") == "bot_reply"
    ]

    return BuildContextOutput(
        ticket_context=context,
        ticket_title=title,
        always_on_context=always_on_text,
        diagnostics_allowed=diagnostics_allowed,
        auto_publish_ticket_types=auto_publish_ticket_types,
    )
