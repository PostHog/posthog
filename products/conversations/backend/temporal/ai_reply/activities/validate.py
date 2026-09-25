from __future__ import annotations

import json as json_module
from dataclasses import replace
from typing import Literal

import structlog
from pydantic import BaseModel, Field
from temporalio import activity

from posthog.llm.gateway_client import get_async_anthropic_gateway_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.conversations.backend.temporal.ai_reply.activities.draft import _hydrate_chunks
from products.conversations.backend.temporal.ai_reply.constants import (
    MAX_CHUNK_CONTENT_CHARS,
    MAX_EXCERPT_CHARS,
    MAX_SAFETY_REVIEWED_CHARS,
    MAX_VALIDATE_EVIDENCE_CHARS,
    TICKET_TYPE_HINTS,
    VALIDATE_BLOCKERS,
    VALIDATOR_MODEL,
)
from products.conversations.backend.temporal.ai_reply.llms import (
    anthropic_output_config,
    anthropic_text,
    create_message,
    llm_attempts,
    strip_json_fence,
    tracing_kwargs,
)
from products.conversations.backend.temporal.ai_reply.schemas import ValidateInput, ValidateOutput, coerce_unit_interval

logger = structlog.get_logger(__name__)


class ValidateResult(BaseModel):
    grounded: bool
    coverage: float = Field(description="Fraction of the customer's question the reply addresses, from 0 to 1")
    confidence: float = Field(description="Confidence the reply is correct and complete, from 0 to 1")
    missing: list[str] = Field(description="Topics the customer asked about that the reply or chunks do not cover")
    blocker: Literal["none", "customer_info", "knowledge", "contradiction"]


@activity.defn
async def support_validate_activity(input: ValidateInput) -> ValidateOutput:
    """Validate the draft reply against the source chunks for groundedness and coverage."""
    async with Heartbeater():
        return replace(await _validate(input), llm_attempts=llm_attempts())


async def _validate(input: ValidateInput) -> ValidateOutput:
    # Only the cited chunks need rehydrating — fetch their content from the DB by id.
    cited_ids = [cid for cid in input.chunk_ids if cid in set(input.citations)]
    cited_chunks = await database_sync_to_async(_hydrate_chunks, thread_sensitive=False)(input.team_id, cited_ids)
    evidence_parts = [f"[{c['chunk_id']}] {c['content'][:MAX_CHUNK_CONTENT_CHARS]}" for c in cited_chunks]
    # Ground against evidence the agent gathered via MCP tools too (e.g. docs-search URLs),
    # not just the seed chunks — otherwise docs-based answers always look unsupported.
    seen_refs = {c["chunk_id"] for c in cited_chunks}
    for s in input.sources or []:
        ref = s.get("ref", "")
        excerpt = s.get("excerpt", "")
        if excerpt and ref not in seen_refs:
            seen_refs.add(ref)
            evidence_parts.append(f"[{ref}] {excerpt[:MAX_EXCERPT_CHARS]}")
    chunks_text = "\n\n".join(evidence_parts)[:MAX_VALIDATE_EVIDENCE_CHARS]

    type_hint = TICKET_TYPE_HINTS.get(input.ticket_type, "")
    system = f"""You validate whether a support reply is grounded in the provided knowledge base chunks.

Ticket type: {input.ticket_type}. {type_hint} Judge coverage against what THIS type of question needs answered.

Return a JSON object with these keys:
- grounded: boolean — true unless some factual claim in the reply CONTRADICTS the cited chunks. A claim does not need to appear verbatim in an excerpt; it only needs to be consistent with (not refuted by) the sources. Reasonable paraphrase, summary, and combination of the cited facts is grounded. Only mark grounded=false when the reply asserts something the sources actively contradict, or invents a highly specific detail — such as an exact price, version number, date, or limit — that cannot be inferred from the sources at all.
- coverage: float 0-1 — what fraction of the customer's question does the reply address?
- confidence: float 0-1 — overall confidence the reply is correct and complete.
- missing: list of strings — topics the customer asked about that are NOT covered by the reply or chunks.
- blocker: one of none, customer_info, knowledge, contradiction.
  none: the reply can be judged on groundedness and coverage alone.
  customer_info: a fact only the customer can provide is missing (SDK, project, error text).
  knowledge: docs and the knowledge base do not cover what was asked.
  contradiction: the reply asserts something the sources refute.

Return ONLY the JSON object, no other text."""

    user_content = f"""TICKET CONTEXT:
{input.ticket_context[:MAX_SAFETY_REVIEWED_CHARS]}

REPLY:
{input.reply}

CITED CHUNKS:
{chunks_text}"""

    client = get_async_anthropic_gateway_client(product="conversations", team_id=input.team_id)
    message = await create_message(
        client,
        model=VALIDATOR_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        **anthropic_output_config(ValidateResult),
        **tracing_kwargs(input.trace_id, input.ticket_id),
    )
    content = anthropic_text(message)

    try:
        parsed = json_module.loads(strip_json_fence(content))
        blocker = parsed.get("blocker", "knowledge")
        if blocker not in VALIDATE_BLOCKERS:
            blocker = "knowledge"
        return ValidateOutput(
            grounded=bool(parsed.get("grounded", False)),
            coverage=coerce_unit_interval(parsed.get("coverage", 0.0)),
            confidence=coerce_unit_interval(parsed.get("confidence", 0.0)),
            missing=list(parsed.get("missing", [])),
            blocker=blocker,
        )
    except (json_module.JSONDecodeError, ValueError, TypeError):
        logger.warning("support_reply_validate_parse_failed", raw=str(content)[:200])
        return ValidateOutput(
            grounded=False, coverage=0.0, confidence=0.0, missing=["parse_failure"], blocker="knowledge"
        )
