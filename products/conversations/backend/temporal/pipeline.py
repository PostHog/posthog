from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from products.conversations.backend.temporal.ai_reply.activities.build_context import support_build_context_activity
from products.conversations.backend.temporal.ai_reply.activities.classify import support_classify_activity
from products.conversations.backend.temporal.ai_reply.activities.draft import support_draft_activity
from products.conversations.backend.temporal.ai_reply.activities.persist_knowledge_gap import (
    support_persist_knowledge_gap_activity,
)
from products.conversations.backend.temporal.ai_reply.activities.persist_reply import support_persist_reply_activity
from products.conversations.backend.temporal.ai_reply.activities.record_triage import support_record_triage_activity
from products.conversations.backend.temporal.ai_reply.activities.refine_queries import support_refine_queries_activity
from products.conversations.backend.temporal.ai_reply.activities.retrieve import support_retrieve_activity
from products.conversations.backend.temporal.ai_reply.activities.review_reply import support_review_reply_activity
from products.conversations.backend.temporal.ai_reply.activities.safety_filter import support_safety_filter_activity
from products.conversations.backend.temporal.ai_reply.activities.validate import support_validate_activity
from products.conversations.backend.temporal.ai_reply.constants import (
    MAX_ATTEMPTS,
    MAX_SAFETY_REVIEWED_CHARS,
    SCORE_THRESHOLD,
)
from products.conversations.backend.temporal.ai_reply.schemas import (
    ClassifyInput,
    DraftInput,
    PersistKnowledgeGapInput,
    PersistReplyInput,
    RecordTriageInput,
    RefineQueriesInput,
    RetrieveInput,
    ReviewReplyInput,
    SafetyFilterInput,
    SupportReplyInput,
    ValidateInput,
)

# These modules (Django models, langchain, pydantic models, etc.) are non-deterministic
# and/or define classes the Temporal workflow sandbox proxies — importing them inside the
# sandbox crashes workflow validation. Only the activities touch them at runtime, so pass
# them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    pass


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@workflow.defn(name="support-reply-pipeline")
class SupportReplyWorkflow:
    """Grounded self-validating support reply pipeline.

    Loop: refine -> retrieve -> draft -> validate
    Iterate while validate score < threshold, hard cap MAX_ATTEMPTS.
    Feed validate.missing back into refine on each iteration.

    Triage lifecycle (`ai_triage.status`), recorded via `_record_triage`:
      - in_progress: run started, context built, draft loop not yet terminal.
      - done: a terminal branch set `outcome`; recorded in `finally`. An empty
        `outcome` (unexpected crash) is never marked done.

    Terminal outcomes (`ai_triage.result`), exactly one per finished run:
      - blocked_unsafe: input safety gate rejected the incoming ticket
        (prompt-injection / exfiltration) before any LLM draft work.
      - skipped_unactionable: classifier judged the ticket has no answerable
        question (spam / bare feedback); draft loop skipped. Distinct from
        escalated_no_reply, which means we tried and failed.
      - persisted: a draft cleared SCORE_THRESHOLD and passed the output review
        gate; auto-sent to the customer (allow_bot_reply=True).
      - blocked_unsafe_reply: a draft was good enough to send but the output
        review gate caught a PII leak / exfil, so it was withheld.
      - escalated_with_best: exhausted MAX_ATTEMPTS without clearing the
        threshold, but the best draft (>0 confidence) passed output review and
        was saved as an internal/human-gated note (allow_bot_reply=False).
      - escalated_no_reply: exhausted MAX_ATTEMPTS with no usable draft at all;
        nothing persisted, ticket handed to a human cold.
    """

    @workflow.run
    async def run(self, input: SupportReplyInput) -> str:
        team_id = input.team_id
        ticket_id = input.ticket_id
        wf_info = workflow.info()
        _triage_base: dict[str, Any] = {
            "schema_version": 1,
            "workflow_id": wf_info.workflow_id,
            "run_id": wf_info.run_id,
        }

        async def _record_triage(patch: dict[str, Any]) -> None:
            # Best-effort observability metadata — must never break the support pipeline, so
            # swallow failures here rather than letting a triage write abort the run.
            try:
                await workflow.execute_activity(
                    support_record_triage_activity,
                    RecordTriageInput(team_id=team_id, ticket_id=ticket_id, patch={**_triage_base, **patch}),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                workflow.logger.warning("support_reply: failed to record triage", status=patch.get("status"))

        async def _persist_gaps(gap_missing: list[str], gap_ticket_type: str, gap_outcome: str) -> None:
            """Best-effort: record knowledge gaps without breaking the pipeline."""
            if not gap_missing:
                return
            try:
                await workflow.execute_activity(
                    support_persist_knowledge_gap_activity,
                    PersistKnowledgeGapInput(
                        team_id=team_id,
                        ticket_id=ticket_id,
                        missing=gap_missing,
                        ticket_type=gap_ticket_type,
                        outcome=gap_outcome,
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                workflow.logger.warning("support_reply: failed to persist knowledge gaps")

        # Build context
        ctx_output = await workflow.execute_activity(
            support_build_context_activity,
            input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Record lifecycle start
        await _record_triage(
            {
                "status": "in_progress",
                "started_at": workflow.now().isoformat(),
            }
        )

        # Slice once so the safety filter and draft agent see the exact same ticket text.
        reviewed_context = ctx_output.ticket_context[:MAX_SAFETY_REVIEWED_CHARS]

        # --- Outcome tracking: set before each return, recorded in finally ---
        outcome: dict[str, Any] = {}
        try:
            # Input safety gate: block prompt-injection / exfiltration attempts before any LLM
            # draft work. Mirrored from the signals product's safety_filter_activity pattern.
            safety_output = await workflow.execute_activity(
                support_safety_filter_activity,
                SafetyFilterInput(team_id=input.team_id, ticket_context=reviewed_context),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not safety_output.safe:
                workflow.logger.info(
                    "support_reply: ticket blocked by safety filter",
                    threat_type=safety_output.threat_type,
                )
                outcome = {"result": "blocked_unsafe"}
                return "blocked_unsafe"

            # Triage once, up front (not per attempt): the type + seed queries bias the whole
            # loop, and `unactionable` tickets (spam/bare feedback) skip the expensive draft loop.
            classify_output = await workflow.execute_activity(
                support_classify_activity,
                ClassifyInput(team_id=input.team_id, ticket_context=reviewed_context),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if classify_output.ticket_type == "unactionable":
                # Distinct outcome from `escalated_no_reply` (which means "tried and exhausted
                # retries"): this ticket had no answerable question, so downstream routing/metrics
                # can treat spam/feedback differently from genuine failed attempts.
                workflow.logger.info("support_reply: ticket classified unactionable; skipping draft loop")
                outcome = {"result": "skipped_unactionable", "ticket_type": "unactionable"}
                return "skipped_unactionable"

            ticket_type = classify_output.ticket_type
            needs_diagnostics = classify_output.needs_diagnostics and ctx_output.diagnostics_allowed
            # Whether this reply would be auto-sent to the (untrusted) author on its channel.
            # Keeps customer-data read scopes off any auto-publishable draft (see draft.py).
            auto_publishable = ticket_type in ctx_output.auto_publish_ticket_types

            missing: list[str] = []
            prior_citations: list[str] = []
            prior_reply: str = ""
            best_reply: str = ""
            best_confidence: float = 0.0
            best_citations: list[str] = []
            best_sources: list[dict[str, str]] = []
            best_missing: list[str] = []

            for attempt in range(MAX_ATTEMPTS):
                widen = attempt > 0

                # Refine queries
                refine_output = await workflow.execute_activity(
                    support_refine_queries_activity,
                    RefineQueriesInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        missing=missing,
                        ticket_type=ticket_type,
                        seed_queries=classify_output.seed_queries,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                # Retrieve + rerank
                retrieve_output = await workflow.execute_activity(
                    support_retrieve_activity,
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
                    support_draft_activity,
                    DraftInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        chunk_ids=retrieve_output.chunk_ids,
                        prior_reply=prior_reply,
                        prior_missing=missing,
                        always_on_context=ctx_output.always_on_context,
                        ticket_type=ticket_type,
                        needs_diagnostics=needs_diagnostics,
                        diagnostics_allowed=ctx_output.diagnostics_allowed,
                        auto_publishable=auto_publishable,
                    ),
                    start_to_close_timeout=timedelta(minutes=20),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                # Validate
                validate_output = await workflow.execute_activity(
                    support_validate_activity,
                    ValidateInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        reply=draft_output.reply,
                        citations=draft_output.citations,
                        chunk_ids=retrieve_output.chunk_ids,
                        sources=draft_output.sources,
                        ticket_type=ticket_type,
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
                    best_sources = draft_output.sources
                    best_missing = validate_output.missing

                if validate_output.confidence >= SCORE_THRESHOLD:
                    # Output safety gate: check for PII leaks / exfil before the reply reaches
                    # the (untrusted) ticket author.
                    review_output = await workflow.execute_activity(
                        support_review_reply_activity,
                        ReviewReplyInput(
                            team_id=input.team_id,
                            ticket_context=reviewed_context,
                            reply=draft_output.reply,
                            sources=draft_output.sources,
                            ticket_type=ticket_type,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    if not review_output.safe:
                        workflow.logger.info(
                            "support_reply: reply blocked by output review",
                            reason=review_output.reason,
                        )
                        outcome = {
                            "result": "blocked_unsafe_reply",
                            "ticket_type": ticket_type,
                            "needs_diagnostics": needs_diagnostics,
                            "diagnostics_allowed": ctx_output.diagnostics_allowed,
                            "confidence": validate_output.confidence,
                            "attempts": attempt + 1,
                        }
                        return "blocked_unsafe_reply"

                    await workflow.execute_activity(
                        support_persist_reply_activity,
                        PersistReplyInput(
                            team_id=input.team_id,
                            ticket_id=input.ticket_id,
                            reply=draft_output.reply,
                            citations=draft_output.citations,
                            confidence=validate_output.confidence,
                            ticket_type=ticket_type,
                            allow_bot_reply=True,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    if validate_output.missing:
                        await _persist_gaps(validate_output.missing, ticket_type, "persisted")
                    outcome = {
                        "result": "persisted",
                        "ticket_type": ticket_type,
                        "needs_diagnostics": needs_diagnostics,
                        "diagnostics_allowed": ctx_output.diagnostics_allowed,
                        "confidence": validate_output.confidence,
                        "attempts": attempt + 1,
                        "missing": validate_output.missing,
                    }
                    return f"persisted (confidence={validate_output.confidence:.2f}, attempts={attempt + 1})"

                # Prepare for next iteration: refine the best-validated draft (not necessarily
                # the last one, which may have drifted) using the gaps the validator found in it.
                missing = best_missing
                prior_citations = best_citations
                prior_reply = best_reply

            # Exhausted attempts — persist best if we have one with non-zero confidence
            if best_reply and best_confidence > 0:
                review_output = await workflow.execute_activity(
                    support_review_reply_activity,
                    ReviewReplyInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        reply=best_reply,
                        sources=best_sources,
                        ticket_type=ticket_type,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if not review_output.safe:
                    workflow.logger.info(
                        "support_reply: reply blocked by output review",
                        reason=review_output.reason,
                    )
                    outcome = {
                        "result": "blocked_unsafe_reply",
                        "ticket_type": ticket_type,
                        "needs_diagnostics": needs_diagnostics,
                        "diagnostics_allowed": ctx_output.diagnostics_allowed,
                        "confidence": best_confidence,
                        "attempts": MAX_ATTEMPTS,
                    }
                    return "blocked_unsafe_reply"

                await workflow.execute_activity(
                    support_persist_reply_activity,
                    PersistReplyInput(
                        team_id=input.team_id,
                        ticket_id=input.ticket_id,
                        reply=best_reply,
                        citations=best_citations,
                        confidence=best_confidence,
                        ticket_type=ticket_type,
                        allow_bot_reply=False,
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if best_missing:
                    await _persist_gaps(best_missing, ticket_type, "escalated_with_best")
                outcome = {
                    "result": "escalated_with_best",
                    "ticket_type": ticket_type,
                    "needs_diagnostics": needs_diagnostics,
                    "diagnostics_allowed": ctx_output.diagnostics_allowed,
                    "confidence": best_confidence,
                    "attempts": MAX_ATTEMPTS,
                    "missing": best_missing,
                }
                return f"escalated_with_best (confidence={best_confidence:.2f})"

            if best_missing:
                await _persist_gaps(best_missing, ticket_type, "escalated_no_reply")
            outcome = {
                "result": "escalated_no_reply",
                "ticket_type": ticket_type,
                "needs_diagnostics": needs_diagnostics,
                "diagnostics_allowed": ctx_output.diagnostics_allowed,
                "attempts": MAX_ATTEMPTS,
                "missing": best_missing,
            }
            return "escalated_no_reply"
        finally:
            # `outcome` is only set on the workflow's own terminal branches; on an unexpected
            # crash it stays empty, so we never mark a failed run as "done".
            if outcome:
                await _record_triage(
                    {
                        **outcome,
                        "status": "done",
                        "finished_at": workflow.now().isoformat(),
                    }
                )
