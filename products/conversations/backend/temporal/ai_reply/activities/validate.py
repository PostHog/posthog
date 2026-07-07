from __future__ import annotations

import json as json_module

import structlog
from temporalio import activity

from posthog.llm.gateway_client import get_async_anthropic_gateway_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.conversations.backend.temporal.ai_reply.activities.draft import _hydrate_chunks
from products.conversations.backend.temporal.ai_reply.constants import TICKET_TYPE_HINTS, VALIDATOR_MODEL
from products.conversations.backend.temporal.ai_reply.llms import anthropic_text, create_message, strip_json_fence
from products.conversations.backend.temporal.ai_reply.schemas import ValidateInput, ValidateOutput

logger = structlog.get_logger(__name__)


@activity.defn
async def support_validate_activity(input: ValidateInput) -> ValidateOutput:
    """Validate the draft reply against the source chunks for groundedness and coverage."""
    async with Heartbeater():
        return await _validate(
            input.team_id,
            input.ticket_context,
            input.reply,
            input.citations,
            input.chunk_ids,
            input.sources,
            input.ticket_type,
            input.trace_id,
            input.ticket_id,
        )


async def _validate(
    team_id: int,
    ticket_context: str,
    reply: str,
    citations: list[str],
    chunk_ids: list[str],
    sources: list[dict[str, str]] | None = None,
    ticket_type: str = "how_to",
    trace_id: str = "",
    ticket_id: str = "",
) -> ValidateOutput:
    # Only the cited chunks need rehydrating — fetch their content from the DB by id.
    cited_ids = [cid for cid in chunk_ids if cid in set(citations)]
    cited_chunks = await database_sync_to_async(_hydrate_chunks, thread_sensitive=False)(team_id, cited_ids)
    evidence_parts = [f"[{c['chunk_id']}] {c['content'][:500]}" for c in cited_chunks]
    # Ground against evidence the agent gathered via MCP tools too (e.g. docs-search URLs),
    # not just the seed chunks — otherwise docs-based answers always look unsupported.
    seen_refs = {c["chunk_id"] for c in cited_chunks}
    for s in sources or []:
        ref = s.get("ref", "")
        excerpt = s.get("excerpt", "")
        if excerpt and ref not in seen_refs:
            seen_refs.add(ref)
            evidence_parts.append(f"[{ref}] {excerpt[:500]}")
    chunks_text = "\n\n".join(evidence_parts)

    type_hint = TICKET_TYPE_HINTS.get(ticket_type, "")
    system = f"""You validate whether a support reply is grounded in the provided knowledge base chunks.

Ticket type: {ticket_type}. {type_hint} Judge coverage against what THIS type of question needs answered.

Return a JSON object with these keys:
- grounded: boolean — true unless some factual claim in the reply CONTRADICTS the cited chunks. A claim does not need to appear verbatim in an excerpt; it only needs to be consistent with (not refuted by) the sources. Reasonable paraphrase, summary, and combination of the cited facts is grounded. Only mark grounded=false when the reply asserts something the sources actively contradict, or invents a highly specific detail — such as an exact price, version number, date, or limit — that cannot be inferred from the sources at all.
- coverage: float 0-1 — what fraction of the customer's question does the reply address?
- confidence: float 0-1 — overall confidence the reply is correct and complete.
- missing: list of strings — topics the customer asked about that are NOT covered by the reply or chunks.

Return ONLY the JSON object, no other text."""

    user_content = f"""TICKET CONTEXT:
{ticket_context[:3000]}

REPLY:
{reply}

CITED CHUNKS:
{chunks_text[:6000]}"""

    client = get_async_anthropic_gateway_client(product="conversations", team_id=team_id)
    message = await create_message(
        client,
        model=VALIDATOR_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        metadata={"user_id": trace_id} if trace_id else None,
        extra_headers={"x-posthog-property-ticket_id": ticket_id} if ticket_id else None,
    )
    content = anthropic_text(message)

    try:
        parsed = json_module.loads(strip_json_fence(content))
        return ValidateOutput(
            grounded=bool(parsed.get("grounded", False)),
            coverage=float(parsed.get("coverage", 0.0)),
            confidence=float(parsed.get("confidence", 0.0)),
            missing=list(parsed.get("missing", [])),
        )
    except (json_module.JSONDecodeError, ValueError, TypeError):
        logger.warning("support_reply_validate_parse_failed", raw=str(content)[:200])
        return ValidateOutput(grounded=False, coverage=0.0, confidence=0.0, missing=["parse_failure"])
