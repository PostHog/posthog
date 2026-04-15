from __future__ import annotations

import os
import uuid
import asyncio
import logging
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from braintrust import EvalAsync, EvalCase, EvalHooks
from posthoganalytics import Posthog

from .config import AgentArtifacts, SandboxedEvalCase
from .log_sink import append_case_scores, build_case_dir, write_case_logs
from .runner import run_eval_case

if TYPE_CHECKING:
    from .conftest import SandboxedDemoData
from .acp_log import ParsedLog, parse_log
from .scorers import wrap_scorers
from .trace_events import emit_evaluation_events, emit_trace_events, emit_trace_root

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
    pytestconfig: pytest.Config,
    sandboxed_demo_data: SandboxedDemoData,
    is_public: bool = False,
    no_send_logs: bool = True,
    posthog_client: Posthog | None = None,
):
    """Run a sandboxed agent evaluation suite via Braintrust.

    For each ``SandboxedEvalCase``, creates a Task, triggers the temporal workflow
    (sandbox provisioning, agent-server, prompt delivery, cleanup), polls S3 logs
    for results, and feeds parsed artifacts to the scorers.

    ``sandboxed_demo_data.make_context(case_name)`` is invoked once per case and
    returns a freshly isolated ``CustomPromptSandboxContext`` (own org/team/user)
    so cases can't pollute each other's state.
    """
    # Generate a unique experiment ID per eval run
    experiment_id = str(uuid.uuid4())

    # Shared lookups populated by task(), read after EvalAsync completes.
    agent_trace_id_lookup: dict[str, str] = {}
    # Per-case metadata for emitting $ai_trace root events after scoring.
    case_trace_meta: dict[str, dict[str, Any]] = {}

    # Local disk sink for raw agent logs — lets an agent iterating on the
    # harness read back what happened without round-tripping through Braintrust.
    run_log_dir = build_case_dir(experiment_name, experiment_id)
    log_dirs: set[Path] = getattr(pytestconfig, "_sandboxed_eval_log_dirs", set())
    log_dirs.add(run_log_dir)
    pytestconfig._sandboxed_eval_log_dirs = log_dirs  # type: ignore[attr-defined]

    # Wrap scorers with tracing if PostHog client is available
    scorer_traces: dict[tuple[str, str], str] = {}
    if posthog_client:
        active_scorers, scorer_traces = wrap_scorers(
            scorers, posthog_client, experiment_id, experiment_name, agent_trace_id_lookup
        )
    else:
        active_scorers = list(scorers)

    # Filter cases by --eval flag if provided
    case_filter = pytestconfig.option.eval if hasattr(pytestconfig.option, "eval") else None

    eval_cases: list[EvalCase] = []
    for case in cases:
        if case_filter and case_filter not in case.name:
            continue
        eval_cases.append(
            EvalCase(
                input={"name": case.name, "prompt": case.prompt, "repo_fixture": case.repo_fixture},
                expected=case.expected,
                metadata=case.metadata,
            )
        )

    async def task(input: dict[str, Any], hooks: EvalHooks) -> dict[str, Any] | None:
        eval_case = SandboxedEvalCase(
            name=input["name"],
            prompt=input["prompt"],
            repo_fixture=input.get("repo_fixture", ""),
        )

        try:
            # The factory does Django ORM work (fresh org/team/user, ClickHouse
            # copy SQL, PSQL person sync). Django's async-safety guard rejects
            # sync ORM calls from async contexts, so run it in a worker thread.
            sandbox_context = await asyncio.to_thread(sandboxed_demo_data.make_context, eval_case.name)
            result = await run_eval_case(eval_case, sandbox_context)

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
                print(f"[eval-logs] {eval_case.name}: {paths.case_dir}")  # noqa: T201
            except Exception:
                logger.exception("Failed to write local eval logs for '%s'", eval_case.name)

            return result.artifacts.model_dump() | {
                "last_message": last_message,
                "messages": messages,
                "raw_log": result.raw_log,
            }
        except Exception as e:
            logger.exception("Eval task failed for '%s'", input.get("name", "?"))
            return AgentArtifacts(
                exit_code=-1,
                stderr=f"Eval runner error: {e}",
            ).model_dump()

    project_name = f"sandboxed-agent-{experiment_name}" if is_public else experiment_name

    timeout = 60 * 15  # 15 minutes per case
    if os.getenv("EVAL_MODE") == "offline":
        timeout = 60 * 60

    result = await EvalAsync(
        project_name,
        data=eval_cases,
        task=task,
        scores=active_scorers,
        timeout=timeout,
        max_concurrency=2,
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
            print(  # noqa: T201
                f"\nPostHog evaluations: "
                f"https://us.posthog.com/project/2/llm-analytics/evaluations/offline/experiments/"
                f"{experiment_id}?offline_date_from=-1d\n"
            )
        except Exception:
            logger.exception("Failed to emit evaluation events for '%s'", experiment_name)

    if os.getenv("EXPORT_EVAL_RESULTS"):
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")

    return result


SandboxedPublicEval = partial(SandboxedEval, is_public=True, no_send_logs=False)
"""Sandboxed evaluation case that is publicly accessible."""

SandboxedPrivateEval = partial(SandboxedEval, is_public=False, no_send_logs=True)
"""Sandboxed evaluation case that is not accessible publicly."""
