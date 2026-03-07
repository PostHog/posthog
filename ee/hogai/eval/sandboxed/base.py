from __future__ import annotations

import os
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from braintrust import EvalAsync, EvalCase

from .config import AgentArtifacts, SandboxedEvalCase, SandboxEvalConfig
from .runner import SandboxedEvalRunner


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    repo_fixtures: dict[str, Path],
    scorers: Sequence[Any],
    pytestconfig: pytest.Config,
    config: SandboxEvalConfig | None = None,
    is_public: bool = False,
    no_send_logs: bool = True,
):
    """Run a sandboxed agent evaluation suite via Braintrust.

    This wraps Braintrust's ``EvalAsync`` to handle the sandboxed agent lifecycle:
    for each ``SandboxedEvalCase``, it provisions a Docker sandbox, runs the agent,
    collects artifacts, and feeds them to the scorers.

    Args:
        experiment_name: Name for the Braintrust experiment.
        cases: Eval cases to run.
        repo_fixtures: Map of fixture name → local repo path (built by ``create_temp_repo``).
        scorers: Braintrust-compatible scorers that receive ``AgentArtifacts`` as output.
        pytestconfig: pytest config (for ``--eval`` case filtering).
        config: Sandbox configuration (defaults to ``SandboxEvalConfig()``).
        is_public: Whether to make the Braintrust experiment public.
        no_send_logs: Whether to suppress log sending to Braintrust.
    """
    runner = SandboxedEvalRunner(config)

    # Filter cases by --eval flag if provided
    case_filter = pytestconfig.option.eval if hasattr(pytestconfig.option, "eval") else None

    # Convert SandboxedEvalCase to Braintrust EvalCase
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
        case_name = input["name"]
        prompt = input["prompt"]
        fixture_name = input["repo_fixture"]

        repo_path = repo_fixtures.get(fixture_name)
        if repo_path is None:
            return AgentArtifacts(
                exit_code=-1,
                stderr=f"Repo fixture '{fixture_name}' not found in repo_fixtures map",
            ).model_dump()

        eval_case = SandboxedEvalCase(
            name=case_name,
            prompt=prompt,
            repo_fixture=fixture_name,
        )

        try:
            artifacts = runner.run_eval_case(eval_case, repo_path)
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
        max_concurrency=2,  # sandboxed evals are resource-heavy
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
