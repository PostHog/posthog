from __future__ import annotations

import os
import logging
from collections.abc import Sequence
from functools import partial
from typing import Any

import pytest

from braintrust import EvalAsync, EvalCase, EvalHooks
from posthoganalytics import Posthog

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

from .config import AgentArtifacts, SandboxedEvalCase
from .runner import run_eval_case
from .trace_capture import emit_evaluation_events, emit_trace_events

logger = logging.getLogger(__name__)


def _log_conversation_spans(hooks: EvalHooks, conversation: list[dict[str, Any]]) -> None:
    """Log each conversation turn as a child span so Braintrust renders a trace tree."""
    for turn in conversation:
        role = turn.get("role", "system")
        content = turn.get("content", "")
        span_type = "llm" if role == "assistant" and not turn.get("tool") else "function"
        name = turn.get("name") or role

        with hooks.span.start_span(name=name, span_attributes={"type": span_type}) as span:
            if role == "user":
                span.log(input=content)
            elif role == "assistant" and turn.get("tool"):
                span.log(input=turn.get("title", ""), output=content)
            elif role == "assistant":
                span.log(output=content)
            else:
                span.log(metadata={"message": content})


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    pytestconfig: pytest.Config,
    sandbox_context: CustomPromptSandboxContext,
    is_public: bool = False,
    no_send_logs: bool = True,
    posthog_client: Posthog | None = None,
):
    """Run a sandboxed agent evaluation suite via Braintrust.

    For each ``SandboxedEvalCase``, creates a Task, triggers the temporal workflow
    (sandbox provisioning, agent-server, prompt delivery, cleanup), polls S3 logs
    for results, and feeds parsed artifacts to the scorers.
    """
    # Filter cases by --eval flag if provided
    case_filter = pytestconfig.option.eval if hasattr(pytestconfig.option, "eval") else None

    eval_cases: list[EvalCase] = []
    for case in cases:
        if case_filter and case_filter not in case.name:
            continue
        eval_cases.append(
            EvalCase(
                input={"name": case.name, "prompt": case.prompt, "repo_fixture": case.repo_fixture},
                expected=case.expected.model_dump(),
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
            result = await run_eval_case(eval_case, sandbox_context)

            # Store trace_id in metadata so evaluation events can link to the trace
            if result.trace_id:
                hooks.metadata["trace_id"] = result.trace_id

            if result.conversation:
                _log_conversation_spans(hooks, result.conversation)

            # Emit trace events to PostHog
            if posthog_client and result.raw_log:
                try:
                    emit_trace_events(
                        posthog_client,
                        trace_id=result.trace_id,
                        case_name=eval_case.name,
                        prompt=eval_case.prompt,
                        raw_log=result.raw_log,
                        duration=result.artifacts.duration_seconds,
                        artifacts_summary=result.artifacts.model_dump(),
                    )
                except Exception:
                    logger.exception("Failed to emit trace events for '%s'", eval_case.name)

            return result.artifacts.model_dump()
        except Exception as e:
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
        scores=scorers,
        timeout=timeout,
        max_concurrency=2,
        update=True,
        is_public=is_public,
        no_send_logs=no_send_logs,
    )

    # Emit evaluation events to PostHog
    if posthog_client and result.results:
        try:
            experiment_id = emit_evaluation_events(posthog_client, experiment_name, result.results)
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
