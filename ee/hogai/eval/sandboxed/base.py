from __future__ import annotations

import time
import uuid
import asyncio
import logging
from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from braintrust import EvalAsync, EvalCase, EvalHooks
from braintrust.framework import EvalResultWithSummary

from .acp_log import ParsedLog, parse_log
from .config import AgentArtifacts, SandboxedEvalCase
from .harness.reporting import QUIET_REPORTER
from .log_sink import append_case_scores, build_case_dir, write_case_logs
from .runner import run_eval_case
from .scorers import wrap_scorers
from .trace_events import emit_evaluation_events, emit_trace_events, emit_trace_root

if TYPE_CHECKING:
    from .harness.context import EvalContext

logger = logging.getLogger(__name__)


def _get_last_assistant_text(parsed: ParsedLog) -> str:
    """Extract the last assistant message text from the final generation."""
    for gen in reversed(parsed.generations):
        if not gen.output_content:
            continue
        texts = [b.get("text", "") for b in gen.output_content if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(t for t in texts if t)
        if text:
            return text
    return ""


def _log_conversation_spans(hooks: EvalHooks, parsed: ParsedLog) -> None:
    """Log each conversation message as a child span so Braintrust renders a trace tree.

    Uses the same Anthropic-format messages as PostHog trace capture.
    """
    for msg in parsed.messages:
        role = msg.get("role", "system")
        content = msg.get("content", "")

        # Anthropic format: content can be a string or list of content blocks
        if isinstance(content, list):
            # Render content blocks for display
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    parts.append(f"[tool_use: {block.get('name', '?')}]")
                elif block_type == "tool_result":
                    result_text = str(block.get("content", ""))[:500]
                    is_error = block.get("is_error", False)
                    prefix = "[tool_result error]" if is_error else "[tool_result]"
                    parts.append(f"{prefix} {result_text}")
            display_content = "\n".join(parts)
        else:
            display_content = str(content)

        if role == "assistant":
            # Check if this message contains tool_use blocks
            has_tool_use = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            )
            span_type = "function" if has_tool_use else "llm"
            name = "tool_call" if has_tool_use else "agent"
        elif role == "user":
            has_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            span_type = "function"
            name = "tool_result" if has_tool_result else "user"
        else:
            span_type = "function"
            name = role

        with hooks.span.start_span(name=name, span_attributes={"type": span_type}) as span:
            if role == "user":
                span.log(input=display_content)
            elif role == "assistant":
                span.log(output=display_content)
            else:
                span.log(metadata={"message": display_content})

    # Also log non-AI spans (console, errors)
    for span_desc in parsed.spans:
        with hooks.span.start_span(name=span_desc.span_name, span_attributes={"type": "function"}) as span:
            span.log(metadata={"message": span_desc.content})


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    ctx: EvalContext,
    is_public: bool = False,
    no_send_logs: bool = True,
) -> EvalResultWithSummary:
    """Run a sandboxed agent evaluation suite via Braintrust.

    For each ``SandboxedEvalCase``, creates a Task, triggers the temporal workflow
    (sandbox provisioning, agent-server, prompt delivery, cleanup), polls S3 logs
    for results, and feeds parsed artifacts to the scorers.

    ``ctx.demo_data.make_context(case_name)`` is invoked once per case and
    returns a freshly isolated ``CustomPromptSandboxContext`` (own org/team/user)
    so cases can't pollute each other's state.

    Everything the suite needs (demo data, analytics client, case filter,
    concurrency limits, reporter) comes off ``ctx``; suites run concurrently on
    one event loop, so total sandbox load is bounded by ``ctx.sandbox_slots``.
    """
    # Generate a unique experiment ID per eval run
    experiment_id = str(uuid.uuid4())

    posthog_client = ctx.posthog_client

    # Shared lookups populated by task(), read after EvalAsync completes.
    agent_trace_id_lookup: dict[str, str] = {}
    # Per-case metadata for emitting $ai_trace root events after scoring.
    case_trace_meta: dict[str, dict[str, Any]] = {}

    # Local disk sink for raw agent logs — lets an agent iterating on the
    # harness read back what happened without round-tripping through Braintrust.
    run_log_dir = build_case_dir(experiment_name, experiment_id)
    ctx.log_dirs.add(run_log_dir)

    # Wrap scorers with tracing if PostHog client is available
    scorer_traces: dict[tuple[str, str], str] = {}
    if posthog_client:
        active_scorers, scorer_traces = wrap_scorers(
            scorers, posthog_client, experiment_id, experiment_name, agent_trace_id_lookup
        )
    else:
        active_scorers = list(scorers)

    case_filter = ctx.case_filter

    # Closure-scoped lookup so callable hooks on SandboxedEvalCase (e.g. `setup`)
    # can be re-bound inside `task()` — they don't survive Braintrust's JSON
    # round-trip, but the original case objects do.
    cases_by_name: dict[str, SandboxedEvalCase] = {c.name: c for c in cases}

    eval_cases: list[EvalCase] = []
    for case in cases:
        if case_filter and case_filter not in case.name:
            continue
        eval_cases.append(
            EvalCase(
                input={
                    "name": case.name,
                    "prompt": case.prompt,
                    "repo_fixture": case.repo_fixture,
                },
                expected=case.expected,
                metadata=case.metadata,
            )
        )

    async def task(input: dict[str, Any], hooks: EvalHooks) -> dict[str, Any] | None:
        case_started = time.monotonic()
        eval_case = SandboxedEvalCase(
            name=input["name"],
            prompt=input["prompt"],
            repo_fixture=input.get("repo_fixture", ""),
        )
        original_case = cases_by_name.get(input["name"])
        seed_result: dict[str, Any] = {}

        try:
            # Hold a global sandbox slot for only the sandbox-owning window:
            # demo-data copy, setup hook, and the agent run. Everything after —
            # log parsing, span building, trace emission, scoring — runs once the
            # slot is freed, so a live sandbox never waits on post-processing.
            async with ctx.sandbox_slots:
                # ``ctx.demo_slots`` is a separate, smaller semaphore bounding
                # concurrent ClickHouse demo-data copies. With Modal the sandbox
                # semaphore is effectively unbounded, so it can no longer double
                # as that protection.
                async with ctx.demo_slots:
                    # The factory does Django ORM work. Django's async-safety
                    # guard rejects sync ORM calls from async contexts, so run it
                    # in a worker thread.
                    sandbox_context = await asyncio.to_thread(ctx.demo_data.make_context, eval_case.name)
                if original_case is not None and original_case.setup is not None:
                    try:
                        seed_result = await asyncio.to_thread(original_case.setup, sandbox_context)
                    except Exception:
                        logger.exception("Setup hook failed for '%s'", eval_case.name)
                        raise
                # Budget the agent run from slot acquisition, so time spent queued
                # on the sandbox semaphore can never eat into a case's timeout.
                result = await asyncio.wait_for(
                    run_eval_case(eval_case, sandbox_context),
                    timeout=ctx.per_case_timeout_seconds,
                )

            # Store trace_id in metadata so evaluation events can link to the trace
            if result.trace_id:
                hooks.metadata["trace_id"] = result.trace_id
                agent_trace_id_lookup[eval_case.name] = result.trace_id
            hooks.metadata["artifacts"] = result.artifacts.model_dump()

            # Parse the log once, use for both Braintrust spans and PostHog trace capture
            last_message = ""
            messages: list[dict[str, Any]] = []
            if result.raw_log:
                parsed = parse_log(result.raw_log, initial_prompt=eval_case.prompt)
                _log_conversation_spans(hooks, parsed)
                last_message = _get_last_assistant_text(parsed)
                messages = parsed.messages

                if posthog_client:
                    try:
                        emit_trace_events(
                            posthog_client,
                            trace_id=result.trace_id,
                            experiment_id=experiment_id,
                            experiment_name=experiment_name,
                            case_name=eval_case.name,
                            parsed=parsed,
                        )
                        # Store metadata for emit_trace_root (called after scoring)
                        case_trace_meta[eval_case.name] = {
                            "prompt": eval_case.prompt,
                            "duration": result.artifacts.duration_seconds,
                            "first_timestamp": parsed.first_timestamp,
                            "last_message": last_message,
                            "artifacts_summary": result.artifacts.model_dump(),
                            "token_usage": parsed.total_token_usage,
                        }
                    except Exception:
                        logger.exception("Failed to emit trace events for '%s'", eval_case.name)

            try:
                paths = write_case_logs(
                    case_dir=run_log_dir,
                    case_name=eval_case.name,
                    raw_log=result.raw_log or "",
                    artifacts=result.artifacts.model_dump(),
                    prompt=eval_case.prompt,
                    duration=result.artifacts.duration_seconds,
                    last_message=last_message,
                    token_usage=case_trace_meta.get(eval_case.name, {}).get("token_usage"),
                )
                await ctx.reporter.case_log_path(eval_case.name, paths.case_dir)
            except Exception:
                logger.exception("Failed to write local eval logs for '%s'", eval_case.name)

            return result.artifacts.model_dump() | {
                "last_message": last_message,
                "messages": messages,
                "raw_log": result.raw_log,
                "seed": seed_result,
                "prompt": eval_case.prompt,
            }
        except Exception as e:
            logger.exception("Eval task failed for '%s'", input.get("name", "?"))
            return AgentArtifacts(
                exit_code=-1,
                stderr=f"Eval runner error: {e}",
            ).model_dump()
        finally:
            # Report on both paths so the reporter's live case counter never stalls.
            await ctx.reporter.case_done(
                experiment_name,
                eval_case.name,
                duration_seconds=time.monotonic() - case_started,
            )

    project_name = f"sandboxed-agent-{experiment_name}" if is_public else experiment_name

    result = await EvalAsync(
        project_name,
        data=eval_cases,
        task=task,
        scores=active_scorers,
        # Our global ``ctx.sandbox_slots`` semaphore is the only limiter that
        # should bind. Braintrust's own per-suite limiter must never gate, so
        # let it admit every case at once.
        max_concurrency=max(len(eval_cases), 1),
        # Braintrust's timeout wraps the whole task invocation, including any time
        # a case spends queued on our sandbox semaphore — so a queued case would
        # be killed before it ever acquired a sandbox. The real budget is the
        # ``asyncio.wait_for`` above, which starts only after slot acquisition.
        timeout=None,
        # Suites share one stdout; the quiet reporter stops each experiment from
        # dumping its own score table into the interleaved stream.
        reporter=QUIET_REPORTER,
        update=True,
        is_public=is_public,
        no_send_logs=no_send_logs,
    )

    # Append final scores to local summary files for every case we wrote.
    if result.results:
        for eval_result in result.results:
            case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
            if not case_name:
                continue
            try:
                append_case_scores(run_log_dir, case_name, dict(eval_result.scores or {}))
            except Exception:
                logger.exception("Failed to append scores to local log summary for '%s'", case_name)

    # Emit evaluation events and trace roots to PostHog (after scoring)
    if posthog_client and result.results:
        try:
            emit_evaluation_events(posthog_client, experiment_id, experiment_name, result.results, scorer_traces)
            # Emit $ai_trace root events now that scores are available
            for eval_result in result.results:
                case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
                trace_id = agent_trace_id_lookup.get(case_name)
                meta = case_trace_meta.get(case_name)
                if trace_id and meta:
                    emit_trace_root(
                        posthog_client,
                        trace_id=trace_id,
                        experiment_id=experiment_id,
                        experiment_name=experiment_name,
                        case_name=case_name,
                        prompt=meta["prompt"],
                        duration=meta["duration"],
                        first_timestamp=meta["first_timestamp"],
                        last_message=meta.get("last_message", ""),
                        artifacts_summary=meta.get("artifacts_summary"),
                        scores=eval_result.scores,
                        token_usage=meta.get("token_usage"),
                    )
            posthog_client.flush()
            await ctx.reporter.posthog_evaluations_url(experiment_id)
        except Exception:
            logger.exception("Failed to emit evaluation events for '%s'", experiment_name)

    # Hand the summary to the reporter: suites don't return their Braintrust
    # result up to the orchestrator, so this is the only place the final table
    # and the EXPORT_EVAL_RESULTS jsonl can read per-scorer scores from.
    await ctx.reporter.record_summary(experiment_name, result.summary)

    return result


SandboxedPublicEval = partial(SandboxedEval, is_public=True, no_send_logs=False)
"""Sandboxed evaluation case that is publicly accessible."""

SandboxedPrivateEval = partial(SandboxedEval, is_public=False, no_send_logs=True)
"""Sandboxed evaluation case that is not accessible publicly."""
