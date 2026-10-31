from __future__ import annotations

from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.conversations.backend.ai.llms import llm_attempts
from products.conversations.backend.temporal.ai_reply.schemas import WriteBriefInput, WriteBriefOutput
from products.conversations.backend.ticket_brief.writer import write_brief


@activity.defn(name="support-write-brief")
@close_db_connections
async def support_write_brief_activity(input: WriteBriefInput) -> WriteBriefOutput:
    """Restate the ticket as a structured brief and store it on the ticket.

    Never raises for a bad brief. A ticket with no brief shows no panel, which is the state
    every ticket is in today, so failing here must not fail the reply the run exists to draft.
    """
    async with Heartbeater():
        outcome = await write_brief(
            team_id=input.team_id,
            ticket_id=input.ticket_id,
            ticket_context=input.ticket_context,
            trace_id=input.trace_id,
        )
    return WriteBriefOutput(written=outcome.written, reason=outcome.reason, llm_attempts=llm_attempts())
