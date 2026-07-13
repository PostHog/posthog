from __future__ import annotations

import json
import time
import uuid
import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.temporal.common.client import async_connect

from products.tasks.backend.facade.agents import CustomPromptSandboxContext, create_task_and_trigger, poll_for_turn
from products.tasks.backend.facade.temporal import ProcessTaskWorkflow

from .config import AgentArtifacts, SandboxedEvalCase
from .harness.providers import SandboxProviderStrategy

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle

logger = logging.getLogger(__name__)

__all__ = ["run_eval_case"]


async def _end_workflow(handle: WorkflowHandle, reason: str) -> None:
    """Shut the case's ``ProcessTaskWorkflow`` down so a timed-out or errored case
    stops burning LLM tokens and its sandbox stops billing.

    Signals ``complete_task`` with a failed status (the same path the multi-turn
    session's ``end`` takes), falling back to a hard cancel if the signal can't be
    delivered. Either route runs the workflow's own ``cleanup_sandbox``, so this is
    provider-agnostic. A double failure only warns — teardown must not mask the
    original error being propagated.
    """
    try:
        await handle.signal(ProcessTaskWorkflow.complete_task, args=["failed", reason])
    except Exception:
        try:
            await handle.cancel()
        except Exception:
            logger.warning("Failed to tear down workflow for eval case (reason=%s)", reason, exc_info=True)


@dataclass
class EvalCaseResult:
    artifacts: AgentArtifacts
    trace_id: str = ""
    raw_log: str = ""


async def run_eval_case(
    case: SandboxedEvalCase,
    context: CustomPromptSandboxContext,
    *,
    provider: SandboxProviderStrategy,
) -> EvalCaseResult:
    """Run an eval case using the full Task -> temporal workflow -> log polling pipeline.

    On any failure — including the ``CancelledError`` the caller's ``wait_for``
    timeout raises into this coroutine — the case's workflow is signalled to shut
    down before the exception propagates, so no agent or sandbox is left running.
    """
    trace_id = str(uuid.uuid4())
    logger.info("Starting eval case '%s' (trace=%s) with prompt: %.100s...", case.name, trace_id, case.prompt)
    start = time.monotonic()
    task = None
    handle: WorkflowHandle | None = None
    try:
        # Eval is a test harness — direct use of internals (instead of MTS) is intentional:
        # the agent isn't asked for structured JSON, and we need full_log for artifact parsing.
        task, task_run = await create_task_and_trigger(case.prompt, context, step_name=case.name)
        # Handle to the case's workflow so a timeout/error can shut the agent down.
        workflow_id = task_run.get_workflow_id(task.id, task_run.id)
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        last_message, full_log_opt, _, _ = await poll_for_turn(
            task_run, verbose=True, output_fn=lambda msg: logger.info("agent: %s", msg)
        )
        full_log = full_log_opt or ""

        duration = time.monotonic() - start
        logger.info(
            "Eval case '%s' completed in %.1fs, log size=%d, last_message=%.200s",
            case.name,
            duration,
            len(full_log),
            last_message or "(none)",
        )
        artifacts = _parse_artifacts_from_log(full_log, duration, agent_finished=True)
        return EvalCaseResult(artifacts=artifacts, trace_id=trace_id, raw_log=full_log)
    except (Exception, asyncio.CancelledError) as e:
        # CancelledError is how the caller's asyncio.wait_for timeout reaches this
        # coroutine; catch it explicitly so we can stop the workflow, then re-raise.
        duration = time.monotonic() - start
        logger.exception("Eval case '%s' failed after %.1fs: %s", case.name, duration, e)
        if handle is not None:
            # Shield so a re-firing cancel can't abort the shutdown signal mid-flight.
            await asyncio.shield(_end_workflow(handle, reason=f"eval case '{case.name}' failed: {e}"))
        raise
    finally:
        if task is not None:
            await asyncio.to_thread(provider.cleanup_case, str(task.id))


def _parse_artifacts_from_log(log_content: str, duration_seconds: float, agent_finished: bool) -> AgentArtifacts:
    """Extract scoring artifacts from JSONL agent logs."""
    tool_outputs: list[dict] = []
    has_error = False

    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue

        # Check for errors
        if notification.get("method") == "_posthog/error":
            has_error = True

        if notification.get("method") != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        session_update = update.get("sessionUpdate")
        if session_update in {"tool_call", "tool_call_update"}:
            tool_outputs.append(update)

    # Extract git diff, file changes, test results from tool outputs
    git_diff = ""
    files_changed: list[str] = []
    test_output = ""
    test_exit_code: int | None = None
    lint_output = ""
    lint_exit_code: int | None = None
    agent_output = ""

    for tool in tool_outputs:
        title = (tool.get("title") or "").lower()
        content = tool.get("content")
        text = ""
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text", "")
        elif isinstance(content, str):
            text = content

        # Detect git diff output
        if "git diff" in title and text:
            git_diff = text

        # Detect git status / changed files
        if ("git diff --name-only" in title or "git status" in title) and text:
            files_changed.extend(f.strip() for f in text.splitlines() if f.strip())

        # Detect test runs
        if ("pytest" in title or "test" in title) and text:
            test_output = text
            # Infer exit code from pytest output patterns
            if "passed" in text and "failed" not in text and "error" not in text.lower():
                test_exit_code = 0
            elif "failed" in text or "error" in text.lower():
                test_exit_code = 1

        # Detect lint runs
        if ("ruff" in title or "lint" in title) and text:
            lint_output = text
            if "All checks passed" in text or not text.strip():
                lint_exit_code = 0
            else:
                lint_exit_code = 1

        # Accumulate all tool output for general context
        if text:
            agent_output += text + "\n"

    return AgentArtifacts(
        exit_code=0 if agent_finished and not has_error else 1,
        stdout=agent_output[:10000],
        stderr="",
        git_diff=git_diff,
        files_changed=files_changed,
        test_exit_code=test_exit_code,
        test_output=test_output[:5000],
        lint_exit_code=lint_exit_code,
        lint_output=lint_output[:5000],
        duration_seconds=duration_seconds,
    )
