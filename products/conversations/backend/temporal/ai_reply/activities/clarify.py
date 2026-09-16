from __future__ import annotations

from django.db import transaction

from temporalio import activity

from posthog.models.comment import Comment
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ai_reply.gate import (
    format_clarifying_question,
    format_suggested_question_comment,
)
from products.conversations.backend.temporal.ai_reply.publish import channel_allows_bot_reply
from products.conversations.backend.temporal.ai_reply.schemas import ClarifyInput, ClarifyOutput, coerce_dataclass


@activity.defn
@close_db_connections
async def support_clarify_activity(input: ClarifyInput) -> ClarifyOutput:
    """Post a clarifying question as a public reply or a private suggested-question note."""
    async with Heartbeater():
        return await database_sync_to_async(_clarify_sync, thread_sensitive=False)(input)


def _has_prior_public_clarification(*, team_id: int, ticket_id: str) -> bool:
    return (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket_id),
            item_context__author_type="AI",
            item_context__persist_as="clarification",
        )
        .exclude(item_context__is_private=True)
        .exists()
    )


def _clarify_sync(input: ClarifyInput) -> ClarifyOutput:
    input = coerce_dataclass(ClarifyInput, input)
    questions = [item.strip() for item in input.clarifying_questions if item and item.strip()]
    question = format_clarifying_question(questions=questions)
    if not question:
        return ClarifyOutput(published=False, question="")

    with transaction.atomic():
        # of=("self",) so select_related("team") does not FOR UPDATE the Team parent row.
        ticket = (
            Ticket.objects.select_related("team")
            .select_for_update(of=("self",))
            .filter(team_id=input.team_id, id=input.ticket_id)
            .first()
        )
        if ticket is None:
            return ClarifyOutput(published=False, question=question)

        publish = (
            input.auto_publishable
            and channel_allows_bot_reply(ticket=ticket, ticket_type=input.ticket_type)
            and not _has_prior_public_clarification(team_id=input.team_id, ticket_id=str(ticket.id))
        )
        if publish:
            content = question
        else:
            content = format_suggested_question_comment(
                questions=questions,
                investigation_summary=input.investigation_summary,
                unknowns=input.unknowns,
                citations=input.citations,
            )

        item_context: dict[str, object] = {
            "author_type": "AI",
            "is_private": not publish,
            "citations": input.citations,
            "confidence": input.confidence,
            "persist_as": "clarification",
            "clarifying_questions": questions,
        }
        if not publish:
            # Public comments are delivered to the customer. Keep investigation notes on
            # the private suggested-question note and on ai_triage instead.
            item_context["investigation_summary"] = input.investigation_summary
            item_context["unknowns"] = input.unknowns

        Comment.objects.create(
            team_id=input.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            item_context=item_context,
        )
        if publish:
            # Coordinator only scans pending + awaiting_clarification. Both have to land in
            # this transaction, or a crash after the question leaves the ticket stuck pending.
            triage = ticket.ai_triage if isinstance(ticket.ai_triage, dict) else {}
            ticket.status = Status.PENDING
            ticket.ai_triage = {**triage, "status": "awaiting_clarification", "clarification_rounds": 1}
            ticket.save(update_fields=["status", "ai_triage", "updated_at"])

    return ClarifyOutput(published=publish, question=question)
