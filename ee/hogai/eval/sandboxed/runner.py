from __future__ import annotations

import json
import time
import uuid
import logging
from dataclasses import dataclass

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, run_prompt

from .config import AgentArtifacts, SandboxedEvalCase

logger = logging.getLogger(__name__)

__all__ = ["run_eval_case"]


@dataclass
class EvalCaseResult:
    artifacts: AgentArtifacts
    trace_id: str = ""
    raw_log: str = ""


async def run_eval_case(
    case: SandboxedEvalCase,
    context: CustomPromptSandboxContext,
) -> EvalCaseResult:
    """Run an eval case using the full Task -> temporal workflow -> log polling pipeline."""
    trace_id = str(uuid.uuid4())
    logger.info("Starting eval case '%s' (trace=%s) with prompt: %.100s...", case.name, trace_id, case.prompt)
    start = time.monotonic()
    try:
        last_message, full_log = await run_prompt(
            case.prompt,
            context,
            step_name=case.name,
            verbose=True,
            output_fn=lambda msg: logger.info("agent: %s", msg),
        )

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
    except Exception as e:
        duration = time.monotonic() - start
        logger.exception("Eval case '%s' failed after %.1fs: %s", case.name, duration, e)
        return EvalCaseResult(
            artifacts=AgentArtifacts(exit_code=1, stderr=str(e), duration_seconds=duration),
            trace_id=trace_id,
        )


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
