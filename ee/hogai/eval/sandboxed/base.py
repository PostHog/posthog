from __future__ import annotations

import os
from collections.abc import Sequence
from functools import partial
from typing import Any

import pytest

from braintrust import EvalAsync, EvalCase

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

from .config import AgentArtifacts, SandboxedEvalCase
from .runner import run_eval_case


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    pytestconfig: pytest.Config,
    sandbox_context: CustomPromptSandboxContext,
    is_public: bool = False,
    no_send_logs: bool = True,
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

    async def task(input: dict[str, Any], expected: dict[str, Any] | None = None, **kwargs) -> dict[str, Any] | None:
        eval_case = SandboxedEvalCase(
            name=input["name"],
            prompt=input["prompt"],
            repo_fixture=input.get("repo_fixture", ""),
        )

        try:
            artifacts = await run_eval_case(eval_case, sandbox_context)
            return artifacts.model_dump()
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
        is_public=is_public,
        no_send_logs=no_send_logs,
    )

    if os.getenv("EXPORT_EVAL_RESULTS"):
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")

    return result


SandboxedPublicEval = partial(SandboxedEval, is_public=True, no_send_logs=False)
"""Sandboxed evaluation case that is publicly accessible."""

SandboxedPrivateEval = partial(SandboxedEval, is_public=False, no_send_logs=True)
"""Sandboxed evaluation case that is not accessible publicly."""
