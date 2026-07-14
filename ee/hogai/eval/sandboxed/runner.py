from __future__ import annotations

import re
import json
import time
import uuid
import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from temporalio.client import WorkflowFailureError

from posthog.temporal.common.client import async_connect

from products.tasks.backend.facade.agents import CustomPromptSandboxContext, create_task_and_trigger, poll_for_turn
from products.tasks.backend.facade.temporal import ProcessTaskWorkflow

from .config import AgentArtifacts, SandboxedEvalCase
from .harness.providers import SandboxProviderStrategy

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle

logger = logging.getLogger(__name__)

__all__ = ["run_eval_case"]

# Word-boundary matches so a tool title like "latest release" doesn't read as a
# test run, and "blueprint" doesn't read as a lint run. These artifacts feed the
# tests-pass / lint-pass scorers, so a false match is a scoring bug.
TEST_TITLE_RE = re.compile(r"\b(pytest|tests?)\b")
LINT_TITLE_RE = re.compile(r"\b(ruff|lint)\b")

WORKFLOW_COMPLETION_GRACE_SECONDS = 60
WORKFLOW_CANCELLATION_GRACE_SECONDS = 30


class WorkflowCleanupError(RuntimeError):
    pass


async def _wait_for_workflow_terminal(handle: WorkflowHandle, timeout_seconds: int) -> bool:
    try:
        await asyncio.wait_for(handle.result(), timeout=timeout_seconds)
    except TimeoutError:
        return False
    except WorkflowFailureError:
        # Cancellation and workflow failure are terminal states. The workflow's
        # finally block has run before Temporal publishes either result.
        return True
    except Exception:
        logger.warning("Could not confirm eval workflow completion", exc_info=True)
        return False
    return True


async def _finish_workflow(handle: WorkflowHandle, *, status: str, reason: str | None) -> bool:
    """Request a terminal state and wait for the workflow's sandbox cleanup."""
    signaled = False
    try:
        await handle.signal(ProcessTaskWorkflow.complete_task, args=[status, reason])
        signaled = True
    except Exception:
        logger.warning("Could not signal eval workflow status=%s", status, exc_info=True)

    if signaled and await _wait_for_workflow_terminal(handle, WORKFLOW_COMPLETION_GRACE_SECONDS):
        return True

    try:
        await handle.cancel()
    except Exception:
        logger.warning("Could not cancel eval workflow after status=%s", status, exc_info=True)

    return await _wait_for_workflow_terminal(handle, WORKFLOW_CANCELLATION_GRACE_SECONDS)


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

    The function returns only after the workflow has reached a terminal state, so
    its sandbox cleanup cannot lag behind a successful case. Failures and caller
    cancellation preserve their original outcome even when cleanup cannot be
    confirmed.
    """
    trace_id = str(uuid.uuid4())
    logger.info("Starting eval case '%s' (trace=%s) with prompt: %.100s...", case.name, trace_id, case.prompt)
    start = time.monotonic()
    task = None
    handle: WorkflowHandle | None = None
    completion_task: asyncio.Task[bool] | None = None
    try:
        # Eval is a test harness — direct use of internals (instead of MTS) is intentional:
        # the agent isn't asked for structured JSON, and we need full_log for artifact parsing.
        task, task_run = await create_task_and_trigger(case.prompt, context, step_name=case.name)
        # Register the task so the end-of-run sweep stays scoped to this run's sandboxes.
        provider.register_task(str(task.id))
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
        completion_task = asyncio.create_task(_finish_workflow(handle, status="completed", reason=None))
        cleanup_confirmed = await asyncio.shield(completion_task)
        if not cleanup_confirmed:
            raise WorkflowCleanupError(
                f"Eval case '{case.name}' finished, but its workflow cleanup could not be confirmed"
            )
        return EvalCaseResult(artifacts=artifacts, trace_id=trace_id, raw_log=full_log)
    except (Exception, asyncio.CancelledError) as e:
        # CancelledError is how the caller's asyncio.wait_for timeout reaches this
        # coroutine; catch it explicitly so we can stop the workflow, then re-raise.
        duration = time.monotonic() - start
        logger.exception("Eval case '%s' failed after %.1fs: %s", case.name, duration, e)
        cleanup_confirmed = False
        if completion_task is not None:
            # A case timeout can arrive while successful workflow cleanup is
            # already running. Let that bounded task settle instead of sending a
            # conflicting failed completion signal.
            cleanup_confirmed = await asyncio.shield(completion_task)
        elif handle is not None and not isinstance(e, WorkflowCleanupError):
            cleanup_confirmed = await asyncio.shield(
                _finish_workflow(handle, status="failed", reason=f"eval case '{case.name}' failed: {e}")
            )
        if handle is not None and not cleanup_confirmed:
            logger.warning("Eval workflow cleanup could not be confirmed for case '%s'", case.name)
        raise
    finally:
        if task is not None:
            try:
                await asyncio.to_thread(provider.cleanup_case, str(task.id))
            except Exception:
                logger.warning("Provider cleanup failed for eval task %s", task.id, exc_info=True)


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
        if TEST_TITLE_RE.search(title) and text:
            test_output = text
            # Infer exit code from pytest output patterns
            if "passed" in text and "failed" not in text and "error" not in text.lower():
                test_exit_code = 0
            elif "failed" in text or "error" in text.lower():
                test_exit_code = 1

        # Detect lint runs
        if LINT_TITLE_RE.search(title) and text:
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
