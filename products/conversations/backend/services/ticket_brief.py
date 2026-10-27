"""Write one ticket's brief outside Temporal.

The staff button and the management command share this, so an on-demand brief is the same
brief the pipeline writes. It lives here rather than beside the activity so the API layer
never imports the Temporal activity package, which imports back into the API.
"""

from __future__ import annotations

import asyncio

from products.conversations.backend.temporal.ai_reply.activities.build_context import _build_context_sync
from products.conversations.backend.temporal.ai_reply.activities.write_brief import _write_brief
from products.conversations.backend.temporal.ai_reply.schemas import WriteBriefInput, WriteBriefOutput


def write_brief_for_ticket(*, team_id: int, ticket_id: str, respect_opt_in: bool = False) -> WriteBriefOutput:
    """Build the context and write the brief.

    `respect_opt_in` is False here: the point of writing one by hand is to read it before the
    team turns briefs on for every new ticket.
    """
    built = _build_context_sync(team_id, ticket_id)
    if built.ticket_gone:
        return WriteBriefOutput(written=False, reason="ticket_gone")
    return asyncio.run(
        _write_brief(
            WriteBriefInput(team_id=team_id, ticket_id=ticket_id, ticket_context=built.ticket_context),
            respect_opt_in=respect_opt_in,
        )
    )
