from __future__ import annotations

from uuid import UUID

import structlog
from temporalio import activity

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.business_knowledge.backend.logic import get_document_window, rerank_chunks, search_knowledge_for_team
from products.business_knowledge.backend.models import KnowledgeChunk
from products.conversations.backend.temporal.ai_reply.constants import (
    MAX_CHUNKS,
    RERANK_TOP_K,
    RETRIEVE_LIMIT,
    WIDEN_RADIUS,
)
from products.conversations.backend.temporal.ai_reply.schemas import RetrieveInput, RetrieveOutput

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
async def support_retrieve_activity(input: RetrieveInput) -> RetrieveOutput:
    """Search BK + rerank. On widen attempts, also fetch document windows around prior citations."""
    async with Heartbeater():
        return await database_sync_to_async(_retrieve_sync, thread_sensitive=False)(
            input.team_id, input.queries, input.prior_citation_chunk_ids, input.widen
        )


def _retrieve_sync(
    team_id: int, queries: list[str], prior_citation_chunk_ids: list[str], widen: bool
) -> RetrieveOutput:
    team = Team.objects.select_related("organization").get(id=team_id)
    all_results = []
    seen_chunk_ids: set[str] = set()

    for query in queries:
        results = search_knowledge_for_team(team, query, limit=RETRIEVE_LIMIT)
        reranked = rerank_chunks(team, query, results, top_k=RERANK_TOP_K)
        for r in reranked:
            cid = str(r.chunk_id)
            if cid not in seen_chunk_ids:
                seen_chunk_ids.add(cid)
                all_results.append(r)

    if widen and prior_citation_chunk_ids:
        for cid_str in prior_citation_chunk_ids[:5]:
            # Citations can be doc URLs (from the docs-search MCP tool) rather than BK
            # chunk UUIDs — only BK chunks can be widened via get_document_window, so
            # skip anything that isn't a UUID instead of treating it as an error.
            try:
                chunk_uuid = UUID(cid_str)
            except ValueError:
                continue
            try:
                # KnowledgeChunk is fail-closed (TeamScopedManager) — scope explicitly
                # since we're outside any request context (Temporal activity).
                chunk = KnowledgeChunk.objects.for_team(team_id).get(id=chunk_uuid)
                window = get_document_window(
                    team_id=team_id,
                    document_id=chunk.document_id,
                    center_ordinal=chunk.ordinal,
                    radius=WIDEN_RADIUS,
                )
                for r in window:
                    wid = str(r.chunk_id)
                    if wid not in seen_chunk_ids:
                        seen_chunk_ids.add(wid)
                        all_results.append(r)
            except Exception:
                logger.warning("support_reply_widen_failed", chunk_id=cid_str, exc_info=True)

    return RetrieveOutput(chunk_ids=[str(r.chunk_id) for r in all_results[:MAX_CHUNKS]])
