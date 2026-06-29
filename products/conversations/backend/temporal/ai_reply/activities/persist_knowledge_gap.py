from __future__ import annotations

import structlog
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import close_db_connections

from products.business_knowledge.backend.logic import upsert_knowledge_gaps
from products.conversations.backend.temporal.ai_reply.schemas import PersistKnowledgeGapInput

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
async def support_persist_knowledge_gap_activity(input: PersistKnowledgeGapInput) -> None:
    """Record knowledge gaps from the support pipeline as suggestions for the BK product."""
    if not input.missing:
        return
    created = await database_sync_to_async(_persist_sync, thread_sensitive=False)(
        input.team_id, input.ticket_id, input.missing, input.ticket_type, input.outcome
    )
    if created:
        logger.info(
            "support_reply: knowledge gaps recorded",
            team_id=input.team_id,
            ticket_id=input.ticket_id,
            created=created,
        )


def _persist_sync(
    team_id: int,
    ticket_id: str,
    missing: list[str],
    ticket_type: str,
    outcome: str,
) -> int:
    return upsert_knowledge_gaps(
        team_id=team_id,
        ticket_id=ticket_id,
        topics=missing,
        ticket_type=ticket_type,
        outcome=outcome,
    )
