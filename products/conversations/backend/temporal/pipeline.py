from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid5

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, RetryState

# These modules (Django models, langchain, pydantic models, etc.) are non-deterministic
# and/or define classes the Temporal workflow sandbox proxies — importing them inside the
# sandbox crashes workflow validation. Only the activities touch them at runtime, so pass
# them through the sandbox unmodified.
with workflow.unsafe.imports_passed_through():
    from products.conversations.backend.temporal.ai_reply.activities.build_context import support_build_context_activity
    from products.conversations.backend.temporal.ai_reply.activities.clarify import support_clarify_activity
    from products.conversations.backend.temporal.ai_reply.activities.classify import support_classify_activity
    from products.conversations.backend.temporal.ai_reply.activities.draft import support_draft_activity
    from products.conversations.backend.temporal.ai_reply.activities.persist_knowledge_gap import (
        support_persist_knowledge_gap_activity,
    )
    from products.conversations.backend.temporal.ai_reply.activities.persist_reply import support_persist_reply_activity
    from products.conversations.backend.temporal.ai_reply.activities.record_triage import support_record_triage_activity
    from products.conversations.backend.temporal.ai_reply.activities.refine_queries import (
        support_refine_queries_activity,
    )
    from products.conversations.backend.temporal.ai_reply.activities.retrieve import support_retrieve_activity
    from products.conversations.backend.temporal.ai_reply.activities.review_reply import support_review_reply_activity
    from products.conversations.backend.temporal.ai_reply.activities.safety_filter import support_safety_filter_activity
    from products.conversations.backend.temporal.ai_reply.activities.validate import support_validate_activity
    from products.conversations.backend.temporal.ai_reply.constants import (
        AI_REPLY_TRACE_NAMESPACE,
        BLOCKER_AWARE_LOOP_PATCH,
        DEFER_KNOWLEDGE_GAPS_UNTIL_RESOLUTION_PATCH,
        LEGACY_MAX_ATTEMPTS,
        MAX_ATTEMPTS,
        MAX_CLARIFICATION_ROUNDS,
        MAX_SAFETY_REVIEWED_CHARS,
        SCORE_THRESHOLD,
        TIERED_CLARIFY_PATCH,
    )
    from products.conversations.backend.temporal.ai_reply.gate import (
        FINDINGS_WITHHELD_REASON,
        decide_reply_action,
        findings_reason_for,
        format_clarifying_question,
        format_findings_comment,
        format_suggested_question_comment,
        should_persist_findings,
    )
    from products.conversations.backend.temporal.ai_reply.schemas import (
        BuildContextOutput,
        ClarifyInput,
        ClarifyOutput,
        ClassifyInput,
        DraftInput,
        DraftOutput,
        PersistKnowledgeGapInput,
        PersistReplyInput,
        PersistReplyOutput,
        RecordTriageInput,
        RefineQueriesInput,
        RetrieveInput,
        ReviewReplyInput,
        SafetyFilterInput,
        SupportReplyInput,
        ValidateInput,
        ValidateOutput,
        coerce_dataclass,
    )


def _bill_llm_activity(*, output: Any | None, error: BaseException | None, maximum_attempts: int) -> int:
    if error is None:
        return max(1, int(getattr(output, "llm_attempts", 1) or 1))
    if isinstance(error, ActivityError) and error.retry_state == RetryState.NON_RETRYABLE_FAILURE:
        return 1
    return maximum_attempts


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@workflow.defn(name="support-reply-pipeline")
class SupportReplyWorkflow:
    """Grounded self-validating support reply pipeline.

    Loop: refine -> retrieve -> draft -> validate
    Iterate while the current gate says retry, hard cap MAX_ATTEMPTS (2) when
    BLOCKER_AWARE_LOOP_PATCH is present. Without that marker, replay uses
    LEGACY_MAX_ATTEMPTS and SCORE_THRESHOLD so the recorded command count matches.

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
      - persisted: a draft cleared the auto-send gate (or SCORE_THRESHOLD when
        BLOCKER_AWARE_LOOP_PATCH is absent) and passed the output review gate;
        auto-sent to the customer (allow_bot_reply=True).
      - suggested: grounded private note with a proposed reply, below auto-send.
      - blocked_unsafe_reply: a draft was good enough to send but the output
        review gate caught a PII leak / exfil, so it was withheld.
      - escalated_with_findings: investigation notes only, never a reply
        presented as an answer.
      - escalated_with_best: histories without BLOCKER_AWARE_LOOP_PATCH: best
        draft (>0 confidence) saved as an internal/human-gated note
        (allow_bot_reply=False). Replay only.
      - escalated_no_reply: exhausted attempts with no usable draft or findings;
        nothing persisted, ticket handed to a human cold.
      - clarified: a public clarifying question was posted; ticket is pending.
      - suggested_clarification: a private suggested question was posted.
    """

    @workflow.run
    async def run(self, input: SupportReplyInput) -> str:
        input = coerce_dataclass(SupportReplyInput, input)
        team_id = input.team_id
        ticket_id = input.ticket_id
        trace_id = str(uuid5(AI_REPLY_TRACE_NAMESPACE, f"support-reply:{team_id}:{ticket_id}"))
        wf_info = workflow.info()
        _triage_base: dict[str, Any] = {
            "schema_version": 1,
            "workflow_id": wf_info.workflow_id,
            "run_id": wf_info.run_id,
        }

        async def _record_triage(patch: dict[str, Any], *, required: bool = False) -> None:
            # Cost and status metadata is best-effort on round 0. Follow-up reopen lives on
            # this write when persist did not run, so a swallow would leave the ticket pending
            # after a completed child id that ALLOW_DUPLICATE_FAILED_ONLY will not retry.
            try:
                await workflow.execute_activity(
                    support_record_triage_activity,
                    RecordTriageInput(team_id=team_id, ticket_id=ticket_id, patch={**_triage_base, **patch}),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                if required:
                    raise
                workflow.logger.warning("support_reply: failed to record triage", extra={"status": patch.get("status")})

        async def _persist_gaps(gap_missing: list[str], gap_ticket_type: str, gap_outcome: str) -> None:
            """Best-effort: record knowledge gaps without breaking the pipeline."""
            if not gap_missing or workflow.patched(DEFER_KNOWLEDGE_GAPS_UNTIL_RESOLUTION_PATCH):
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
        ctx_output = coerce_dataclass(
            BuildContextOutput,
            await workflow.execute_activity(
                support_build_context_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        if input.clarification_round >= 1 and ctx_output.followup_cancelled:
            return "skipped_human_engaged"

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
        draft_task_run_ids: list[str] = []
        llm_calls = 0
        sandbox_seconds = 0.0

        async def _llm(activity_fn: Any, input_value: Any, *, timeout: timedelta, maximum_attempts: int = 3) -> Any:
            nonlocal llm_calls
            try:
                output = await workflow.execute_activity(
                    activity_fn,
                    input_value,
                    start_to_close_timeout=timeout,
                    retry_policy=RetryPolicy(maximum_attempts=maximum_attempts),
                )
                llm_calls += _bill_llm_activity(output=output, error=None, maximum_attempts=maximum_attempts)
                return output
            except Exception as error:
                llm_calls += _bill_llm_activity(output=None, error=error, maximum_attempts=maximum_attempts)
                raise

        async def _persist(persist_input: PersistReplyInput) -> bool:
            persist_input = replace(
                persist_input,
                require_awaiting_clarification=input.clarification_round >= 1,
            )
            raw = await workflow.execute_activity(
                support_persist_reply_activity,
                persist_input,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if input.clarification_round < 1:
                return True
            try:
                posted = coerce_dataclass(PersistReplyOutput, raw).posted
            except TypeError:
                return True
            return posted

        # `finally` reads this on every exit path, including the branches that return
        # before the draft loop starts.
        last_draft: DraftOutput | None = None

        try:
            # Input safety gate: block prompt-injection / exfiltration attempts before any LLM
            # draft work. Mirrored from the signals product's safety_filter_activity pattern.
            safety_output = await _llm(
                support_safety_filter_activity,
                SafetyFilterInput(
                    team_id=input.team_id, ticket_context=reviewed_context, trace_id=trace_id, ticket_id=ticket_id
                ),
                timeout=timedelta(minutes=2),
            )
            if not safety_output.safe:
                workflow.logger.info(
                    "support_reply: ticket blocked by safety filter", extra={"threat_type": safety_output.threat_type}
                )
                outcome = {"result": "blocked_unsafe"}
                return "blocked_unsafe"

            # Triage once, up front (not per attempt): the type + seed queries bias the whole
            # loop, and `unactionable` tickets (spam/bare feedback) skip the expensive draft loop.
            # A clarification follow-up reuses the stored type so the second round cannot flip.
            seed_queries: list[str] = []
            if input.clarification_round >= 1:
                # Skip classify even if triage lost ticket_type, so round two cannot flip.
                ticket_type = ctx_output.prior_ticket_type or "how_to"
                needs_diagnostics = ctx_output.prior_needs_diagnostics and ctx_output.diagnostics_allowed
            else:
                classify_output = await _llm(
                    support_classify_activity,
                    ClassifyInput(
                        team_id=input.team_id, ticket_context=reviewed_context, trace_id=trace_id, ticket_id=ticket_id
                    ),
                    timeout=timedelta(minutes=2),
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
                seed_queries = classify_output.seed_queries
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
            last_validate = None
            attempts_used = 0
            blocker_aware = workflow.patched(BLOCKER_AWARE_LOOP_PATCH)
            tiered_clarify = workflow.patched(TIERED_CLARIFY_PATCH)
            max_attempts = MAX_ATTEMPTS if blocker_aware else LEGACY_MAX_ATTEMPTS
            allow_clarify = tiered_clarify and input.clarification_round < MAX_CLARIFICATION_ROUNDS

            def _base_triage() -> dict[str, Any]:
                return {
                    "ticket_type": ticket_type,
                    "needs_diagnostics": needs_diagnostics,
                    "diagnostics_allowed": ctx_output.diagnostics_allowed,
                }

            def _judge_triage(draft: DraftOutput, validate: ValidateOutput) -> dict[str, Any]:
                return {
                    "verdict": draft.verdict,
                    "blocker": validate.blocker,
                    "draft_confidence": draft.confidence,
                    "validator_confidence": validate.confidence,
                    "coverage": validate.coverage,
                    "grounded": validate.grounded,
                    "citations": list(draft.citations),
                    "investigation_summary": draft.investigation_summary,
                    "unknowns": list(draft.unknowns),
                    "clarifying_questions": list(draft.clarifying_questions),
                    "missing": list(validate.missing),
                }

            for attempt in range(max_attempts):
                attempts_used = attempt + 1
                widen = attempt > 0

                # Refine queries
                refine_output = await _llm(
                    support_refine_queries_activity,
                    RefineQueriesInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        missing=missing,
                        ticket_type=ticket_type,
                        seed_queries=seed_queries,
                        trace_id=trace_id,
                        ticket_id=ticket_id,
                    ),
                    timeout=timedelta(minutes=2),
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
                # read-only MCP tools (team business knowledge, and docs-search when this
                # team uses PostHog docs) and can find sources itself. Seed chunks are a head start.
                if not retrieve_output.chunk_ids:
                    workflow.logger.info("support_reply: no seed chunks; drafting via MCP tools only")

                # Draft via sandbox
                draft_output = coerce_dataclass(
                    DraftOutput,
                    await workflow.execute_activity(
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
                            clarification_round=input.clarification_round,
                            docs_source=ctx_output.docs_source,
                            custom_instructions=ctx_output.custom_instructions,
                        ),
                        start_to_close_timeout=timedelta(minutes=20),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    ),
                )
                sandbox_seconds += draft_output.sandbox_seconds or 0.0

                if draft_output.task_run_id:
                    draft_task_run_ids.append(draft_output.task_run_id)

                # Validate
                validate_output = coerce_dataclass(
                    ValidateOutput,
                    await _llm(
                        support_validate_activity,
                        ValidateInput(
                            team_id=input.team_id,
                            ticket_context=reviewed_context,
                            reply=draft_output.reply,
                            citations=draft_output.citations,
                            chunk_ids=retrieve_output.chunk_ids,
                            sources=draft_output.sources,
                            ticket_type=ticket_type,
                            trace_id=trace_id,
                            ticket_id=ticket_id,
                        ),
                        timeout=timedelta(minutes=2),
                    ),
                )
                last_draft = draft_output
                last_validate = validate_output

                # Track best-so-far by the validator's confidence (the trusted score, same
                # signal the threshold gate uses) — not the draft's self-reported confidence —
                # so an escalated note carries an honest confidence and the best-validated draft.
                if validate_output.confidence >= best_confidence:
                    best_reply = draft_output.reply
                    best_confidence = validate_output.confidence
                    best_citations = draft_output.citations
                    best_sources = draft_output.sources
                    best_missing = validate_output.missing

                if blocker_aware:
                    action = decide_reply_action(
                        grounded=validate_output.grounded,
                        coverage=validate_output.coverage,
                        validator_confidence=validate_output.confidence,
                        draft_confidence=draft_output.confidence,
                        blocker=validate_output.blocker,
                        verdict=draft_output.verdict,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        allow_clarify=allow_clarify,
                    )
                    if action == "clarify" and tiered_clarify:
                        questions = [q for q in draft_output.clarifying_questions if q and q.strip()]
                        if questions:
                            # Review the body customers or agents will actually see. Public
                            # questions are the short ask; private notes include findings.
                            review_text = (
                                format_clarifying_question(questions=questions)
                                if auto_publishable
                                else format_suggested_question_comment(
                                    questions=questions,
                                    investigation_summary=draft_output.investigation_summary,
                                    unknowns=list(draft_output.unknowns),
                                    citations=list(draft_output.citations),
                                )
                            )
                            review_output = await _llm(
                                support_review_reply_activity,
                                ReviewReplyInput(
                                    team_id=input.team_id,
                                    ticket_context=reviewed_context,
                                    reply=review_text,
                                    sources=draft_output.sources,
                                    ticket_type=ticket_type,
                                    trace_id=trace_id,
                                    ticket_id=ticket_id,
                                ),
                                timeout=timedelta(minutes=2),
                            )
                            if review_output.safe:
                                clarify_output = coerce_dataclass(
                                    ClarifyOutput,
                                    await workflow.execute_activity(
                                        support_clarify_activity,
                                        ClarifyInput(
                                            team_id=input.team_id,
                                            ticket_id=input.ticket_id,
                                            ticket_type=ticket_type,
                                            auto_publishable=auto_publishable,
                                            clarifying_questions=questions,
                                            investigation_summary=draft_output.investigation_summary,
                                            unknowns=list(draft_output.unknowns),
                                            citations=list(draft_output.citations),
                                            confidence=validate_output.confidence,
                                        ),
                                        start_to_close_timeout=timedelta(minutes=1),
                                        retry_policy=RetryPolicy(maximum_attempts=3),
                                    ),
                                )
                                result_name = "clarified" if clarify_output.published else "suggested_clarification"
                                if validate_output.missing:
                                    await _persist_gaps(validate_output.missing, ticket_type, result_name)
                                outcome = {
                                    **_base_triage(),
                                    **_judge_triage(draft_output, validate_output),
                                    "result": result_name,
                                    "status": ("awaiting_clarification" if clarify_output.published else "done"),
                                    "clarification_rounds": 1 if clarify_output.published else 0,
                                    "clarifying_questions": questions,
                                    "investigation_summary": draft_output.investigation_summary,
                                    "unknowns": list(draft_output.unknowns),
                                    "confidence": validate_output.confidence,
                                    "attempts": attempt + 1,
                                    "missing": validate_output.missing,
                                }
                                return result_name
                    if action in ("auto_send", "suggest"):
                        review_output = await _llm(
                            support_review_reply_activity,
                            ReviewReplyInput(
                                team_id=input.team_id,
                                ticket_context=reviewed_context,
                                reply=draft_output.reply,
                                sources=draft_output.sources,
                                ticket_type=ticket_type,
                                trace_id=trace_id,
                                ticket_id=ticket_id,
                            ),
                            timeout=timedelta(minutes=2),
                        )
                        if not review_output.safe:
                            workflow.logger.info(
                                "support_reply: reply blocked by output review",
                                extra={"reason": review_output.reason},
                            )
                            outcome = {
                                **_base_triage(),
                                **_judge_triage(draft_output, validate_output),
                                "investigation_summary": "",
                                "unknowns": [],
                                "clarifying_questions": [],
                                "result": "blocked_unsafe_reply",
                                "confidence": validate_output.confidence,
                                "attempts": attempt + 1,
                            }
                            return "blocked_unsafe_reply"

                        result_name = "persisted" if action == "auto_send" else "suggested"
                        if not await _persist(
                            PersistReplyInput(
                                team_id=input.team_id,
                                ticket_id=input.ticket_id,
                                reply=draft_output.reply,
                                citations=draft_output.citations,
                                confidence=validate_output.confidence,
                                ticket_type=ticket_type,
                                allow_bot_reply=action == "auto_send",
                            )
                        ):
                            outcome = {"status": "done"}
                            return "skipped_human_engaged"
                        if validate_output.missing:
                            await _persist_gaps(validate_output.missing, ticket_type, result_name)
                        outcome = {
                            **_base_triage(),
                            **_judge_triage(draft_output, validate_output),
                            "result": result_name,
                            "confidence": validate_output.confidence,
                            "attempts": attempt + 1,
                            "missing": validate_output.missing,
                        }
                        return f"{result_name} (confidence={validate_output.confidence:.2f}, attempts={attempt + 1})"

                    if action == "retry":
                        missing = validate_output.missing
                        prior_citations = draft_output.citations
                        prior_reply = draft_output.reply
                        continue
                    break

                if validate_output.confidence >= SCORE_THRESHOLD:
                    # Output safety gate: check for PII leaks / exfil before the reply reaches
                    # the (untrusted) ticket author.
                    review_output = await _llm(
                        support_review_reply_activity,
                        ReviewReplyInput(
                            team_id=input.team_id,
                            ticket_context=reviewed_context,
                            reply=draft_output.reply,
                            sources=draft_output.sources,
                            ticket_type=ticket_type,
                            trace_id=trace_id,
                            ticket_id=ticket_id,
                        ),
                        timeout=timedelta(minutes=2),
                    )
                    if not review_output.safe:
                        workflow.logger.info(
                            "support_reply: reply blocked by output review", extra={"reason": review_output.reason}
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

                    if not await _persist(
                        PersistReplyInput(
                            team_id=input.team_id,
                            ticket_id=input.ticket_id,
                            reply=draft_output.reply,
                            citations=draft_output.citations,
                            confidence=validate_output.confidence,
                            ticket_type=ticket_type,
                            allow_bot_reply=True,
                        )
                    ):
                        outcome = {"status": "done"}
                        return "skipped_human_engaged"
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

            if blocker_aware:
                if last_draft is not None and last_validate is not None:
                    last_draft = coerce_dataclass(DraftOutput, last_draft)
                    last_validate = coerce_dataclass(ValidateOutput, last_validate)
                    last_verdict = last_draft.verdict
                    last_blocker = last_validate.blocker
                    findings_reason = findings_reason_for(
                        blocker=last_blocker,
                        verdict=last_verdict,
                        grounded=last_validate.grounded,
                    )
                    if should_persist_findings(
                        investigation_summary=last_draft.investigation_summary,
                        unknowns=list(last_draft.unknowns),
                        clarifying_questions=list(last_draft.clarifying_questions),
                        citations=list(last_draft.citations),
                        blocker=last_blocker,
                        verdict=last_verdict,
                    ):
                        findings_text = format_findings_comment(
                            investigation_summary=last_draft.investigation_summary,
                            unknowns=list(last_draft.unknowns),
                            clarifying_questions=list(last_draft.clarifying_questions),
                            findings_reason=findings_reason,
                            citations=list(last_draft.citations),
                        )
                        review_output = await _llm(
                            support_review_reply_activity,
                            ReviewReplyInput(
                                team_id=input.team_id,
                                ticket_context=reviewed_context,
                                reply=findings_text,
                                sources=last_draft.sources,
                                ticket_type=ticket_type,
                                trace_id=trace_id,
                                ticket_id=ticket_id,
                            ),
                            timeout=timedelta(minutes=2),
                        )
                        if not review_output.safe:
                            last_draft = replace(
                                last_draft,
                                citations=[],
                                investigation_summary="",
                                unknowns=[],
                                clarifying_questions=[],
                            )
                            findings_reason = FINDINGS_WITHHELD_REASON
                            findings_text = format_findings_comment(
                                investigation_summary="",
                                unknowns=[],
                                clarifying_questions=[],
                                findings_reason=findings_reason,
                                citations=[],
                            )
                        if not await _persist(
                            PersistReplyInput(
                                team_id=input.team_id,
                                ticket_id=input.ticket_id,
                                reply=findings_text,
                                citations=last_draft.citations,
                                confidence=last_validate.confidence,
                                ticket_type=ticket_type,
                                allow_bot_reply=False,
                                persist_as="findings",
                                investigation_summary=last_draft.investigation_summary,
                                unknowns=list(last_draft.unknowns),
                                clarifying_questions=list(last_draft.clarifying_questions),
                                findings_reason=findings_reason,
                            )
                        ):
                            outcome = {"status": "done"}
                            return "skipped_human_engaged"
                        if last_validate.missing:
                            await _persist_gaps(last_validate.missing, ticket_type, "escalated_with_findings")
                        outcome = {
                            **_base_triage(),
                            **_judge_triage(last_draft, last_validate),
                            "investigation_summary": last_draft.investigation_summary,
                            "unknowns": list(last_draft.unknowns),
                            "clarifying_questions": list(last_draft.clarifying_questions),
                            "result": "escalated_with_findings",
                            "confidence": last_validate.confidence,
                            "attempts": attempts_used,
                            "missing": last_validate.missing,
                        }
                        return f"escalated_with_findings (confidence={last_validate.confidence:.2f})"
                    if last_validate.missing:
                        await _persist_gaps(last_validate.missing, ticket_type, "escalated_no_reply")
                    outcome = {
                        **_base_triage(),
                        **_judge_triage(last_draft, last_validate),
                        "result": "escalated_no_reply",
                        "attempts": attempts_used,
                        "missing": last_validate.missing,
                    }
                    return "escalated_no_reply"
                outcome = {**_base_triage(), "result": "escalated_no_reply", "attempts": max_attempts}
                return "escalated_no_reply"

            # Exhausted attempts — persist best if we have one with non-zero confidence
            if best_reply and best_confidence > 0:
                review_output = await _llm(
                    support_review_reply_activity,
                    ReviewReplyInput(
                        team_id=input.team_id,
                        ticket_context=reviewed_context,
                        reply=best_reply,
                        sources=best_sources,
                        ticket_type=ticket_type,
                        trace_id=trace_id,
                        ticket_id=ticket_id,
                    ),
                    timeout=timedelta(minutes=2),
                )
                if not review_output.safe:
                    workflow.logger.info(
                        "support_reply: reply blocked by output review", extra={"reason": review_output.reason}
                    )
                    outcome = {
                        "result": "blocked_unsafe_reply",
                        "ticket_type": ticket_type,
                        "needs_diagnostics": needs_diagnostics,
                        "diagnostics_allowed": ctx_output.diagnostics_allowed,
                        "confidence": best_confidence,
                        "attempts": LEGACY_MAX_ATTEMPTS,
                    }
                    return "blocked_unsafe_reply"

                if not await _persist(
                    PersistReplyInput(
                        team_id=input.team_id,
                        ticket_id=input.ticket_id,
                        reply=best_reply,
                        citations=best_citations,
                        confidence=best_confidence,
                        ticket_type=ticket_type,
                        allow_bot_reply=False,
                    )
                ):
                    outcome = {"status": "done"}
                    return "skipped_human_engaged"
                if best_missing:
                    await _persist_gaps(best_missing, ticket_type, "escalated_with_best")
                outcome = {
                    "result": "escalated_with_best",
                    "ticket_type": ticket_type,
                    "needs_diagnostics": needs_diagnostics,
                    "diagnostics_allowed": ctx_output.diagnostics_allowed,
                    "confidence": best_confidence,
                    "attempts": LEGACY_MAX_ATTEMPTS,
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
                "attempts": LEGACY_MAX_ATTEMPTS,
                "missing": best_missing,
            }
            return "escalated_no_reply"
        finally:
            # `outcome` is only set on the workflow's own terminal branches; on an unexpected
            # crash it stays empty, so we never mark a failed run as "done".
            if outcome:
                triage_status = outcome.get("status", "done")
                triage_patch = {
                    **outcome,
                    "status": triage_status,
                    "finished_at": workflow.now().isoformat(),
                    "ai_trace_id": trace_id,
                    "draft_task_run_ids": draft_task_run_ids,
                    "cost": {
                        "sandbox_seconds": round(sandbox_seconds, 3),
                        "llm_calls": llm_calls,
                    },
                }
                if last_draft is not None:
                    last_draft = coerce_dataclass(DraftOutput, last_draft)
                    if last_draft.playbook_content_hash:
                        triage_patch["playbook"] = {
                            "layers": list(last_draft.playbook_layers),
                            "default_version": last_draft.playbook_default_version,
                            "posthog_overlay_version": last_draft.playbook_posthog_overlay_version,
                            "content_hash": last_draft.playbook_content_hash,
                            "warnings": list(last_draft.playbook_warnings),
                        }
                followup_reopen = input.clarification_round >= 1
                if followup_reopen:
                    triage_patch["clear_clarification"] = True
                    triage_patch["status"] = "done"
                await _record_triage(triage_patch, required=followup_reopen)
