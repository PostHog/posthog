from __future__ import annotations

import json as json_module
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# These modules (Django models, langchain, pydantic models, etc.) are non-deterministic
# and/or define classes the Temporal workflow sandbox proxies — importing them inside the
# sandbox crashes workflow validation. Only the activities touch them at runtime, so pass
# them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    import structlog
    from pydantic import BaseModel, Field

    from posthog.llm.gateway_client import get_async_anthropic_gateway_client
    from posthog.models.comment import Comment
    from posthog.models.team.team import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.utils import close_db_connections

    from products.business_knowledge.backend.logic import (
        get_chunks_by_ids,
        get_document_window,
        rerank_chunks,
        search_knowledge_for_team,
    )
    from products.business_knowledge.backend.models import KnowledgeChunk
    from products.conversations.backend.ai.suggest import _build_ticket_context
    from products.conversations.backend.models import Ticket
    from products.conversations.backend.temporal.helpers import (
        get_or_create_support_sandbox_env,
        resolve_user_id_for_support,
    )
    from products.tasks.backend.models import Task
    from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext
    from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 5
SCORE_THRESHOLD = 0.5
RERANK_TOP_K = 5
RETRIEVE_LIMIT = 15
DRAFT_POLL_SECONDS = 600
WIDEN_RADIUS = 3

# Temporal records every activity input/output in workflow history (per-payload limit ~2 MiB,
# total history limit ~50 MiB). This loop replays ticket_context + chunks into refine/draft/
# validate across up to MAX_ATTEMPTS iterations, so bound both at the source to keep history
# small. Downstream prompts already slice harder than these caps, so nothing useful is lost.
MAX_TICKET_CONTEXT_CHARS = 16000
MAX_CHUNK_CONTENT_CHARS = 2000
MAX_CHUNKS = 25
# The draft's `sources` are model-controlled (count + excerpt length), so bound them before
# they flow into validate's input and the workflow's best-so-far tracking.
MAX_SOURCES = 25
MAX_EXCERPT_CHARS = 1000

# Plain-LLM utility calls (refine, validate) go through the internal LLM gateway via the
# raw Anthropic SDK — the gateway captures $ai_generation itself, so no langchain wrapper.
UTILITY_MODEL = "claude-haiku-4-5"


def _anthropic_text(message: Any) -> str:
    """Concatenate the text blocks of an Anthropic Messages response."""
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


# ---------------------------------------------------------------------------
# Dataclasses for activity I/O
# ---------------------------------------------------------------------------


@dataclass
class SupportReplyInput:
    team_id: int
    ticket_id: str


@dataclass
class BuildContextOutput:
    ticket_context: str
    ticket_title: str


@dataclass
class RefineQueriesInput:
    team_id: int
    ticket_context: str
    missing: list[str] = field(default_factory=list)


@dataclass
class RefineQueriesOutput:
    queries: list[str]


@dataclass
class RetrieveInput:
    team_id: int
    queries: list[str]
    prior_citation_chunk_ids: list[str] = field(default_factory=list)
    widen: bool = False


@dataclass
class RetrieveOutput:
    # Only chunk ids cross the activity boundary — content is rehydrated from the DB
    # (deterministic) where it's needed, to keep workflow history small.
    chunk_ids: list[str]


@dataclass
class DraftInput:
    team_id: int
    ticket_context: str
    chunk_ids: list[str]
    # Refinement feedback from the previous attempt so the agent improves a good draft
    # instead of re-rolling blind (which tends to drift to a worse, less-grounded answer).
    prior_reply: str = ""
    prior_missing: list[str] = field(default_factory=list)


@dataclass
class DraftOutput:
    reply: str
    citations: list[str]
    confidence: float
    # Evidence the agent actually relied on (BK chunk or doc URL + supporting excerpt).
    # Lets validation ground against sources gathered via MCP tools, not just seed chunks.
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ValidateInput:
    team_id: int
    ticket_context: str
    reply: str
    citations: list[str]
    chunk_ids: list[str]
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ValidateOutput:
    grounded: bool
    coverage: float
    confidence: float
    missing: list[str]


@dataclass
class PersistReplyInput:
    team_id: int
    ticket_id: str
    reply: str
    citations: list[str]
    confidence: float


class SupportReplySource(BaseModel):
    ref: str = Field(description="The citation reference: a chunk_id UUID or a documentation URL")
    excerpt: str = Field(description="The exact text from this source that supports the reply")


class SupportReplyDraft(BaseModel):
    reply: str = Field(description="The drafted reply text")
    citations: list[str] = Field(description="List of chunk_id UUIDs or doc URLs cited in the reply")
    confidence: float = Field(description="Confidence score 0-1 that the reply is correct and grounded")
    sources: list[SupportReplySource] = Field(
        default_factory=list,
        description="Every source used, each with the exact supporting excerpt, so the reply can be validated",
    )


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@activity.defn
@close_db_connections
async def build_context_activity(input: SupportReplyInput) -> BuildContextOutput:
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
    return BuildContextOutput(ticket_context=context, ticket_title=title)


@activity.defn
async def refine_queries_activity(input: RefineQueriesInput) -> RefineQueriesOutput:
    """Use a lightweight LLM to generate search queries from ticket context + missing gaps."""
    async with Heartbeater():
        return await _refine_queries(input.team_id, input.ticket_context, input.missing)


async def _refine_queries(team_id: int, ticket_context: str, missing: list[str]) -> RefineQueriesOutput:
    system = """You are a search query generator for a customer support knowledge base.
Given a customer ticket and optionally a list of missing information from a previous attempt,
generate 2-4 concise search queries that would find the most relevant documentation.
Return ONLY the queries, one per line. No numbering, no explanation."""

    user_parts = [f"Ticket context:\n{ticket_context[:4000]}"]
    if missing:
        user_parts.append("\nMissing from previous attempt:\n" + "\n".join(f"- {m}" for m in missing))

    client = get_async_anthropic_gateway_client(product="conversations", team_id=team_id)
    message = await client.messages.create(
        model=UTILITY_MODEL,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": "\n".join(user_parts)}],
    )
    content = _anthropic_text(message)
    queries = [line.strip() for line in content.strip().split("\n") if line.strip()]
    return RefineQueriesOutput(queries=queries[:4] if queries else ["help"])


@activity.defn
@close_db_connections
async def retrieve_activity(input: RetrieveInput) -> RetrieveOutput:
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


def _hydrate_chunks(team_id: int, chunk_ids: list[str]) -> list[dict[str, Any]]:
    """Rehydrate chunk content + context from the DB for the ids passed across the workflow.

    Deterministic re-fetch — keeps content out of Temporal history. Content is capped here
    (not in the DB) since this is the only place it's materialized for prompts/validation.
    """
    results = get_chunks_by_ids(team_id, [UUID(cid) for cid in chunk_ids])
    return [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "document_title": r.document_title,
            "heading_path": r.heading_path,
            "content": r.content[:MAX_CHUNK_CONTENT_CHARS],
            "source_name": r.source_name,
        }
        for r in results
    ]


@activity.defn
@close_db_connections
async def draft_activity(input: DraftInput) -> DraftOutput:
    """Run a sandbox session with read-only MCP to draft a reply."""
    async with Heartbeater():
        return await _draft_async(
            input.team_id, input.ticket_context, input.chunk_ids, input.prior_reply, input.prior_missing
        )


async def _draft_async(
    team_id: int,
    ticket_context: str,
    chunk_ids: list[str],
    prior_reply: str = "",
    prior_missing: list[str] | None = None,
) -> DraftOutput:
    chunks = await database_sync_to_async(_hydrate_chunks, thread_sensitive=False)(team_id, chunk_ids)
    user_id = await database_sync_to_async(resolve_user_id_for_support, thread_sensitive=False)(team_id)
    env_id = await database_sync_to_async(get_or_create_support_sandbox_env, thread_sensitive=False)(team_id)

    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=None,
        sandbox_environment_id=env_id,
        # business_knowledge:read → BK search/window MCP tools (team's own knowledge).
        # project:read → docs-search MCP tool (Inkeep RAG over the official PostHog docs).
        # Both read-only; persistence happens in a plain activity, so no write scope is needed.
        posthog_mcp_scopes=["business_knowledge:read", "project:read"],
    )

    chunks_text = "\n\n".join(
        f"[chunk_id={c['chunk_id']}] ({c['document_title']} > {c['heading_path']})\n{c['content']}" for c in chunks[:20]
    )

    refinement = ""
    if prior_reply:
        missing_text = "\n".join(f"  - {m}" for m in (prior_missing or [])) or "  - (none specified)"
        refinement = f"""

PREVIOUS ATTEMPT (improve this — do NOT start over from scratch):
{prior_reply[:4000]}

A validator reviewed the previous attempt and flagged these gaps / ungrounded claims:
{missing_text}

Keep everything in the previous reply that was correct and grounded. Fix the flagged issues by
searching for sources that close those gaps, and REMOVE any claim you cannot back with a source
excerpt. Do not introduce new unsupported information."""

    prompt = f"""You are a support agent drafting a reply to a customer ticket.

TICKET CONTEXT:
{ticket_context[:6000]}

KNOWLEDGE BASE RESULTS:
{chunks_text[:12000]}{refinement}

INSTRUCTIONS:
- Draft a helpful, accurate reply to the customer's question.
- Search for sources before answering. The KNOWLEDGE BASE RESULTS above may be empty — that's expected, so use your tools:
  - docs-search: searches the official PostHog documentation (https://posthog.com/docs) via Inkeep. This is the best source for questions about PostHog products and features (billing, support, replay, flags, etc.).
  - business-knowledge-documents-search: searches this team's own business knowledge for team-specific answers.
- Answer ONLY the customer's actual question. Do not pad the reply with adjacent features, options, or tips the customer didn't ask about — every extra claim is something the validator must verify, and unsupported padding lowers the score.
- Every factual sentence must be backed by a source. Cite the exact chunk_id UUID for knowledge-base/business-knowledge chunks, or the doc URL for docs-search results.
- For EVERY citation, also include it in `sources` with the exact supporting excerpt (the snippet of text your tool returned that backs the claim, verbatim). This excerpt is what the validator uses to verify the reply, so do not paraphrase it, and make sure it literally contains the facts your reply states.
- If, after searching, you still can't find sufficient information to answer, set confidence to 0 and reply with a brief note saying you cannot answer.
- Be concise, professional, and empathetic.
- Do NOT make up information — only use what your tools return.

Return your response as a JSON object with keys: reply, citations, confidence, sources (a list of {{ref, excerpt}})."""

    session: MultiTurnSession | None = None
    try:
        session, result = await MultiTurnSession.start(
            prompt,
            context,
            model=SupportReplyDraft,
            step_name="support_reply",
            origin_product=Task.OriginProduct.SUPPORT_REPLY,
            internal=True,
            max_poll_seconds=DRAFT_POLL_SECONDS,
        )
        return DraftOutput(
            reply=result.reply,
            citations=result.citations,
            confidence=result.confidence,
            sources=[{"ref": s.ref, "excerpt": s.excerpt[:MAX_EXCERPT_CHARS]} for s in result.sources[:MAX_SOURCES]],
        )
    finally:
        if session is not None:
            await session.end()


@activity.defn
async def validate_activity(input: ValidateInput) -> ValidateOutput:
    """Validate the draft reply against the source chunks for groundedness and coverage."""
    async with Heartbeater():
        return await _validate(
            input.team_id, input.ticket_context, input.reply, input.citations, input.chunk_ids, input.sources
        )


def _strip_json_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ```) the LLM may wrap JSON in."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        close = s.rfind("```")
        if close != -1:
            s = s[:close]
    return s.strip()


async def _validate(
    team_id: int,
    ticket_context: str,
    reply: str,
    citations: list[str],
    chunk_ids: list[str],
    sources: list[dict[str, str]] | None = None,
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

    system = """You validate whether a support reply is grounded in the provided knowledge base chunks.
Return a JSON object with these keys:
- grounded: boolean — is every factual claim in the reply supported by the cited chunks?
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
    message = await client.messages.create(
        model=UTILITY_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    content = _anthropic_text(message)

    try:
        parsed = json_module.loads(_strip_json_fence(content))
        return ValidateOutput(
            grounded=bool(parsed.get("grounded", False)),
            coverage=float(parsed.get("coverage", 0.0)),
            confidence=float(parsed.get("confidence", 0.0)),
            missing=list(parsed.get("missing", [])),
        )
    except (json_module.JSONDecodeError, ValueError, TypeError):
        logger.warning("support_reply_validate_parse_failed", raw=str(content)[:200])
        return ValidateOutput(grounded=False, coverage=0.0, confidence=0.0, missing=["parse_failure"])


@activity.defn
@close_db_connections
async def persist_reply_activity(input: PersistReplyInput) -> None:
    """Persist the validated reply as a private AI comment on the ticket."""
    async with Heartbeater():
        await database_sync_to_async(_persist_reply_sync, thread_sensitive=False)(
            input.team_id, input.ticket_id, input.reply, input.citations, input.confidence
        )


def _persist_reply_sync(team_id: int, ticket_id: str, reply: str, citations: list[str], confidence: float) -> None:
    Comment.objects.create(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        content=reply,
        item_context={
            "author_type": "AI",
            "is_private": True,
            "citations": citations,
            "confidence": confidence,
        },
    )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@workflow.defn(name="support-reply-pipeline")
class SupportReplyWorkflow:
    """Grounded self-validating support reply pipeline.

    Loop: refine -> retrieve -> draft -> validate
    Iterate while validate score < threshold, hard cap MAX_ATTEMPTS.
    Feed validate.missing back into refine on each iteration.
    """

    @workflow.run
    async def run(self, input: SupportReplyInput) -> str:
        # Build context
        ctx_output = await workflow.execute_activity(
            build_context_activity,
            input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        missing: list[str] = []
        prior_citations: list[str] = []
        prior_reply: str = ""
        best_reply: str = ""
        best_confidence: float = 0.0
        best_citations: list[str] = []
        best_missing: list[str] = []

        for attempt in range(MAX_ATTEMPTS):
            widen = attempt > 0

            # Refine queries
            refine_output = await workflow.execute_activity(
                refine_queries_activity,
                RefineQueriesInput(
                    team_id=input.team_id,
                    ticket_context=ctx_output.ticket_context,
                    missing=missing,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Retrieve + rerank
            retrieve_output = await workflow.execute_activity(
                retrieve_activity,
                RetrieveInput(
                    team_id=input.team_id,
                    queries=refine_output.queries,
                    prior_citation_chunk_ids=prior_citations,
                    widen=widen,
                ),
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Don't short-circuit on empty in-process retrieval — the draft agent has
            # read-only MCP tools (PostHog docs via docs-search, the team's business
            # knowledge) and can find sources itself. Seed chunks are just a head start.
            if not retrieve_output.chunk_ids:
                workflow.logger.info("support_reply: no seed chunks; drafting via MCP tools only")

            # Draft via sandbox
            draft_output = await workflow.execute_activity(
                draft_activity,
                DraftInput(
                    team_id=input.team_id,
                    ticket_context=ctx_output.ticket_context,
                    chunk_ids=retrieve_output.chunk_ids,
                    prior_reply=prior_reply,
                    prior_missing=missing,
                ),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Validate
            validate_output = await workflow.execute_activity(
                validate_activity,
                ValidateInput(
                    team_id=input.team_id,
                    ticket_context=ctx_output.ticket_context,
                    reply=draft_output.reply,
                    citations=draft_output.citations,
                    chunk_ids=retrieve_output.chunk_ids,
                    sources=draft_output.sources,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Track best-so-far by the validator's confidence (the trusted score, same
            # signal the threshold gate uses) — not the draft's self-reported confidence —
            # so an escalated note carries an honest confidence and the best-validated draft.
            if validate_output.confidence >= best_confidence:
                best_reply = draft_output.reply
                best_confidence = validate_output.confidence
                best_citations = draft_output.citations
                best_missing = validate_output.missing

            if validate_output.confidence >= SCORE_THRESHOLD:
                # Persist the reply
                await workflow.execute_activity(
                    persist_reply_activity,
                    PersistReplyInput(
                        team_id=input.team_id,
                        ticket_id=input.ticket_id,
                        reply=draft_output.reply,
                        citations=draft_output.citations,
                        confidence=validate_output.confidence,
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return f"persisted (confidence={validate_output.confidence:.2f}, attempts={attempt + 1})"

            # Prepare for next iteration: refine the best-validated draft (not necessarily
            # the last one, which may have drifted) using the gaps the validator found in it.
            missing = best_missing
            prior_citations = best_citations
            prior_reply = best_reply

        # Exhausted attempts — persist best if we have one with non-zero confidence
        if best_reply and best_confidence > 0:
            await workflow.execute_activity(
                persist_reply_activity,
                PersistReplyInput(
                    team_id=input.team_id,
                    ticket_id=input.ticket_id,
                    reply=best_reply,
                    citations=best_citations,
                    confidence=best_confidence,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return f"escalated_with_best (confidence={best_confidence:.2f})"

        return "escalated_no_reply"
