from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from temporalio import activity

from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ai_reply.gate import format_findings_comment
from products.conversations.backend.temporal.ai_reply.publish import channel_allows_bot_reply
from products.conversations.backend.temporal.ai_reply.schemas import (
    PersistReplyInput,
    PersistReplyOutput,
    coerce_dataclass,
)


@activity.defn
@close_db_connections
async def support_persist_reply_activity(input: PersistReplyInput) -> PersistReplyOutput:
    """Persist the validated reply as an AI comment on the ticket (private note or bot reply per settings)."""
    async with Heartbeater():
        return await database_sync_to_async(_persist_reply_sync, thread_sensitive=False)(input)


def _followup_already_posted(*, team_id: int, ticket_id: str) -> bool:
    return Comment.objects.filter(
        Q(item_context__persist_as="reply") | Q(item_context__persist_as="findings"),
        team_id=team_id,
        scope="conversations_ticket",
        item_id=str(ticket_id),
        item_context__author_type="AI",
    ).exists()


def _persist_reply_sync(input: PersistReplyInput) -> PersistReplyOutput:
    input = coerce_dataclass(PersistReplyInput, input)
    persist_as = input.persist_as
    is_private = True

    with transaction.atomic():
        ticket = None
        if input.require_awaiting_clarification:
            # of=("self",) so select_related("team") does not FOR UPDATE the Team parent row.
            ticket = (
                Ticket.objects.select_related("team")
                .select_for_update(of=("self",))
                .filter(team_id=input.team_id, id=input.ticket_id)
                .first()
            )
            triage = ticket.ai_triage if ticket and isinstance(ticket.ai_triage, dict) else {}
            if triage.get("status") != "awaiting_clarification":
                # Temporal can retry this activity after the first attempt already posted
                # and cleared awaiting. That looks like a human cancel unless we see the note.
                if _followup_already_posted(team_id=input.team_id, ticket_id=input.ticket_id):
                    return PersistReplyOutput(posted=True)
                return PersistReplyOutput(posted=False)
        elif persist_as != "findings" and input.allow_bot_reply:
            ticket = Ticket.objects.select_related("team").filter(team_id=input.team_id, id=input.ticket_id).first()
        # Only how_to replies may be published. diagnostic/account_billing draw on project data and
        # must stay private regardless of the team's ai_reply_modes — guards against stale settings
        # since validation now rejects bot_reply for those types. Controlled by team-level opt-in.
        if persist_as != "findings" and input.allow_bot_reply:
            if ticket and channel_allows_bot_reply(ticket=ticket, ticket_type=input.ticket_type):
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
        Comment.objects.create(
            team_id=input.team_id,
            scope="conversations_ticket",
            item_id=input.ticket_id,
            content=content,
            item_context=item_context,
        )
        if input.require_awaiting_clarification and ticket is not None:
            # Post and reopen together. record_triage is best-effort and would leave the
            # ticket pending forever if it were the only reopen after a completed child id.
            triage = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
            update_fields = ["ai_triage", "updated_at"]
            if ticket.status == Status.PENDING:
                ticket.status = Status.OPEN
                update_fields.append("status")
            ticket.ai_triage = {**triage, "status": "done"}
            ticket.save(update_fields=update_fields)

    return PersistReplyOutput(posted=True)
