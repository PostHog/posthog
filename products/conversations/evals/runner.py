"""Run one support-reply eval fixture through the real Temporal pipeline.

Mocked mode stubs the LLM/sandbox activities and keeps build_context, retrieve,
persist, and record_triage real. Live mode stubs nothing. Either way the workflow
loop in `pipeline.py` is what runs, so scores track that loop rather than a copy.
"""

from __future__ import annotations

import os
import asyncio
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from typing import Any, cast
from uuid import UUID

from unittest.mock import AsyncMock, patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models.comment import Comment

from products.business_knowledge.backend.logic import get_chunks_by_ids, search_knowledge
from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.ai_reply.constants import MAX_CHUNK_CONTENT_CHARS
from products.conversations.backend.temporal.ai_reply.schemas import (
    ClassifyOutput,
    DraftOutput,
    RefineQueriesOutput,
    ReviewReplyOutput,
    SafetyFilterOutput,
    SupportReplyInput,
    ValidateOutput,
)
from products.conversations.backend.temporal.pipeline import (
    SupportReplyWorkflow,
    support_build_context_activity,
    support_classify_activity,
    support_draft_activity,
    support_persist_knowledge_gap_activity,
    support_persist_reply_activity,
    support_record_triage_activity,
    support_refine_queries_activity,
    support_retrieve_activity,
    support_review_reply_activity,
    support_safety_filter_activity,
    support_validate_activity,
)
from products.conversations.evals.constants import LIVE_EVAL_ENV_VAR
from products.conversations.evals.fixtures import SupportReplyFixture
from products.conversations.evals.outcomes import eval_outcome_from_triage
from products.conversations.evals.seeders import SeededCase

ACTIVITIES = "products.conversations.backend.temporal.ai_reply.activities"
SAFETY_MODULE = f"{ACTIVITIES}.safety_filter"
CLASSIFY_MODULE = f"{ACTIVITIES}.classify"
REFINE_MODULE = f"{ACTIVITIES}.refine_queries"
RETRIEVE_MODULE = f"{ACTIVITIES}.retrieve"
DRAFT_MODULE = f"{ACTIVITIES}.draft"
VALIDATE_MODULE = f"{ACTIVITIES}.validate"
REVIEW_MODULE = f"{ACTIVITIES}.review_reply"

WORKFLOW_ACTIVITIES: Sequence[Callable[..., Any]] = cast(
    Sequence[Callable[..., Any]],
    [
        support_build_context_activity,
        support_safety_filter_activity,
        support_classify_activity,
        support_refine_queries_activity,
        support_retrieve_activity,
        support_draft_activity,
        support_validate_activity,
        support_review_reply_activity,
        support_persist_reply_activity,
        support_persist_knowledge_gap_activity,
        support_record_triage_activity,
    ],
)

_MOCKED_WORKFLOW_LOCK = asyncio.Lock()


def live_eval_enabled() -> bool:
    return os.environ.get(LIVE_EVAL_ENV_VAR, "") == "1"


def _chunk_ids_for(source_names: tuple[str, ...], seed: SeededCase) -> list[str]:
    ids: list[str] = []
    for name in source_names:
        ids.extend(seed.chunks_by_source.get(name, ()))
    return ids


def _mocked_draft(fixture: SupportReplyFixture, seed: SeededCase) -> DraftOutput:
    draft = fixture.mocked_draft
    if draft is None:
        return DraftOutput(reply="", citations=[], confidence=0.0)
    citations = _chunk_ids_for(draft.citation_sources, seed)
    sources = [
        {"ref": (_chunk_ids_for((source_name,), seed) or [source_name])[0], "excerpt": excerpt}
        for source_name, excerpt in draft.excerpts
    ]
    return DraftOutput(
        reply=draft.reply,
        citations=citations,
        confidence=draft.confidence,
        sources=sources,
        sandbox_seconds=0.0,
    )


def _mocked_validate(fixture: SupportReplyFixture) -> ValidateOutput:
    validate = fixture.mocked_validate
    if validate is None:
        return ValidateOutput(grounded=False, coverage=0.0, confidence=0.0, missing=[])
    return ValidateOutput(
        grounded=validate.grounded,
        coverage=validate.coverage,
        confidence=validate.confidence,
        missing=list(validate.missing),
    )


def _fts_search(team: Any, query: str, limit: int = 10, **kwargs: Any) -> Any:
    return search_knowledge(team.id, query, limit=limit)


def _identity_rerank(team: Any, query: str, results: Any, *, top_k: int) -> Any:
    return results[:top_k]


@contextmanager
def _mocked_llm_activities(fixture: SupportReplyFixture, seed: SeededCase) -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(
            patch(f"{SAFETY_MODULE}._safety_filter", new_callable=AsyncMock, return_value=SafetyFilterOutput(safe=True))
        )
        stack.enter_context(
            patch(
                f"{CLASSIFY_MODULE}._classify",
                new_callable=AsyncMock,
                return_value=ClassifyOutput(
                    ticket_type=fixture.ticket_type,
                    needs_diagnostics=fixture.needs_diagnostics,
                    seed_queries=list(fixture.seed_queries),
                ),
            )
        )
        stack.enter_context(
            patch(
                f"{REFINE_MODULE}._refine_queries",
                new_callable=AsyncMock,
                return_value=RefineQueriesOutput(queries=list(fixture.seed_queries) or ["support"]),
            )
        )
        stack.enter_context(patch(f"{RETRIEVE_MODULE}.search_knowledge_for_team", side_effect=_fts_search))
        stack.enter_context(patch(f"{RETRIEVE_MODULE}.rerank_chunks", side_effect=_identity_rerank))
        stack.enter_context(
            patch(f"{DRAFT_MODULE}._draft_async", new_callable=AsyncMock, return_value=_mocked_draft(fixture, seed))
        )
        stack.enter_context(
            patch(f"{VALIDATE_MODULE}._validate", new_callable=AsyncMock, return_value=_mocked_validate(fixture))
        )
        stack.enter_context(
            patch(
                f"{REVIEW_MODULE}._review_reply",
                new_callable=AsyncMock,
                return_value=ReviewReplyOutput(safe=True),
            )
        )
        yield


async def _execute_workflow(team_id: int, ticket_id: str) -> str:
    task_queue = f"support-reply-eval-{ticket_id}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SupportReplyWorkflow],
            activities=WORKFLOW_ACTIVITIES,
        ):
            return await env.client.execute_workflow(
                SupportReplyWorkflow.run,
                SupportReplyInput(team_id=team_id, ticket_id=ticket_id),
                id=f"support-reply-eval-{ticket_id}",
                task_queue=task_queue,
            )


def _ai_comment(team_id: int, ticket_id: str) -> Comment | None:
    return (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=ticket_id,
            item_context__author_type="AI",
        )
        .order_by("-created_at")
        .first()
    )


def _source_excerpts(*, team_id: int, citation_ids: list[str]) -> list[dict[str, str]]:
    # Persist stores chunk ids only so Temporal history does not carry the text.
    # The grounding judge needs the excerpts, so rehydrate them the same way validate does.
    uuids: list[UUID] = []
    leftover: list[str] = []
    for ref in citation_ids:
        try:
            uuids.append(UUID(str(ref)))
        except ValueError:
            leftover.append(str(ref))
    excerpts: list[dict[str, str]] = []
    if uuids:
        for result in get_chunks_by_ids(team_id, uuids):
            excerpts.append(
                {
                    "ref": str(result.chunk_id),
                    "excerpt": result.content[:MAX_CHUNK_CONTENT_CHARS],
                    "source_name": result.source_name,
                }
            )
    excerpts.extend({"ref": ref, "excerpt": ""} for ref in leftover)
    return excerpts


def collect_output(
    *,
    fixture: SupportReplyFixture,
    seed: SeededCase,
    workflow_result: str,
    live: bool,
) -> dict[str, Any]:
    ticket = Ticket.objects.filter(id=seed.ticket_id, team_id=seed.team_id).first()
    triage = dict(ticket.ai_triage) if ticket and isinstance(ticket.ai_triage, dict) else {}
    comment = _ai_comment(seed.team_id, seed.ticket_id)
    reply = (comment.content or "") if comment is not None else ""
    raw_citations = []
    if comment is not None and isinstance(comment.item_context, dict):
        raw_citations = [str(c) for c in (comment.item_context.get("citations") or [])]
    citation_source_names = [seed.source_by_chunk[c] for c in raw_citations if c in seed.source_by_chunk]
    clarifying_questions = [q for q in (triage.get("clarifying_questions") or []) if isinstance(q, str)]
    if not clarifying_questions and "?" in reply:
        clarifying_questions = [reply]
    raw_cost = triage.get("cost")
    cost = raw_cost if isinstance(raw_cost, dict) else {}
    eval_outcome = eval_outcome_from_triage(triage)
    return {
        "exit_code": 0,
        "prompt": fixture.prompt,
        "last_message": reply,
        "reply": reply,
        "citations": raw_citations,
        "citation_source_names": citation_source_names,
        "source_excerpts": _source_excerpts(team_id=seed.team_id, citation_ids=raw_citations),
        "clarifying_questions": clarifying_questions,
        "pipeline_result": triage.get("result") or workflow_result,
        "eval_outcome": eval_outcome,
        "ticket_type": triage.get("ticket_type") or fixture.ticket_type,
        "cost": cost,
        "ai_triage": triage,
        "mode": "live" if live else "mocked",
        "seed": {"team_id": seed.team_id, "ticket_id": seed.ticket_id},
    }


async def run_fixture(fixture: SupportReplyFixture, seed: SeededCase, *, live: bool) -> dict[str, Any]:
    """Execute the pipeline for one seeded fixture and return the scorer output dict."""
    try:
        if live:
            workflow_result = await _execute_workflow(seed.team_id, seed.ticket_id)
        else:
            async with _MOCKED_WORKFLOW_LOCK:
                with _mocked_llm_activities(fixture, seed):
                    workflow_result = await _execute_workflow(seed.team_id, seed.ticket_id)
        return await asyncio.to_thread(
            lambda: collect_output(fixture=fixture, seed=seed, workflow_result=workflow_result, live=live)
        )
    except Exception as error:
        return {
            "exit_code": 1,
            "prompt": fixture.prompt,
            "last_message": "",
            "reply": "",
            "citations": [],
            "citation_source_names": [],
            "source_excerpts": [],
            "clarifying_questions": [],
            "pipeline_result": None,
            "eval_outcome": None,
            "ticket_type": fixture.ticket_type,
            "cost": {},
            "error": f"{type(error).__name__}: {error}",
            "mode": "live" if live else "mocked",
            "seed": {"team_id": seed.team_id, "ticket_id": seed.ticket_id},
        }
