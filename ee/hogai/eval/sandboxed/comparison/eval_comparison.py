"""One-off CLI-vs-MCP comparison runner (pytest-invoked benchmark, not a test suite).

Runs each task against all three arms, collects tokens / time / success, and writes
a markdown + JSON report. Reuses the sandboxed eval fixtures for setup.

    pytest ee/hogai/eval/sandboxed/comparison/eval_comparison.py --mcp-mode tools -s

Output: ee/hogai/eval/sandboxed/comparison/out/comparison.{md,json}
(override dir with COMPARISON_OUT, repetitions with COMPARISON_REPS).

=========================  STATUS: scaffold, UNVERIFIED  =========================
The report layer (report.py) is unit-tested. This orchestration is written against
the real harness signatures but has NOT been run end to end (needs Docker + Temporal
+ Braintrust/LLM keys). Open items to validate/finish in the eval env:

  1. CLI-arm steering: the agent must discover the binary via the AGENTS.md steering
     block. That needs `posthog-cli init` run INSIDE the sandbox after start — the
     eval-gated post-start step we deferred. Until it's added, the cli arm relies on
     the agent finding the binary unaided (expect low cli-arm scores). See _install_steering.
  2. MCP suppression target: we monkeypatch `get_sandbox_ph_mcp_configs` in
     start_agent_server; confirm that's the only place MCP servers are injected.
  3. mcp-mode interaction: the sandboxed autouse `_apply_mcp_mode` parametrizes this
     test across modes — run with `--mcp-mode tools` (the loop overrides per arm).
  4. LLM-judge is stubbed (returns None) — wire it to the eval scorers next.
=================================================================================
"""

from __future__ import annotations

import os
import asyncio
import logging
import contextlib
from pathlib import Path

import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

from products.tasks.backend.services.local_cli import ENV_LOCAL_CLI_HOST_PATH

from ee.hogai.eval.sandboxed.acp_log import parse_log
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.runner import run_eval_case

from .arms import ARMS, Arm
from .report import RunResult, render_json, render_markdown
from .tasks import TASKS, ComparisonTask

logger = logging.getLogger(__name__)

REPS = int(os.environ.get("COMPARISON_REPS", "1"))
OUT_DIR = Path(os.environ.get("COMPARISON_OUT", str(Path(__file__).parent / "out")))


@contextlib.contextmanager
def _configure_arm(arm: Arm):
    """Toggle the sandbox config for one arm: binary mount, MCP registration, mode."""
    patches: list = []
    prev_cli = os.environ.get(ENV_LOCAL_CLI_HOST_PATH)

    if not arm.mount_cli:
        os.environ.pop(ENV_LOCAL_CLI_HOST_PATH, None)
    # (when arm.mount_cli, the _sandboxed_local_cli fixture has already set it)

    if arm.suppress_mcp:
        # The CLI arm must NOT have the MCP available, or the agent could use it and
        # contaminate the comparison. TODO(verify): confirm this is the sole injection point.
        patches.append(
            mock.patch(
                "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
                return_value=[],
            )
        )

    settings_override = None
    if arm.mcp_mode and not arm.suppress_mcp:
        base = (settings.SANDBOX_MCP_URL or "").split("?")[0]
        sep = "&" if "?" in base else "?"
        settings_override = override_settings(SANDBOX_MCP_URL=f"{base}{sep}mode={arm.mcp_mode}")

    for p in patches:
        p.start()
    if settings_override:
        settings_override.enable()
    try:
        yield
    finally:
        if settings_override:
            settings_override.disable()
        for p in patches:
            p.stop()
        if prev_cli is None:
            os.environ.pop(ENV_LOCAL_CLI_HOST_PATH, None)
        else:
            os.environ[ENV_LOCAL_CLI_HOST_PATH] = prev_cli


def _install_steering(team_id: int) -> None:
    """Install the AGENTS.md steering block for the CLI arm.

    TODO: requires running `posthog-cli init` inside the sandbox post-start (the deferred
    eval-gated step in start_agent_server). No-op until that lands — tracked in the
    module docstring's open items.
    """


def _tokens(raw_log: str, prompt: str) -> dict[str, int]:
    usage = parse_log(raw_log, initial_prompt=prompt).total_token_usage if raw_log else {}
    cached = int(usage.get("cachedReadTokens", 0)) + int(usage.get("cachedWriteTokens", 0))
    input_t = int(usage.get("inputTokens", 0))
    output_t = int(usage.get("outputTokens", 0))
    total = int(usage.get("totalTokens", 0)) or (input_t + output_t)
    return {"input": input_t, "output": output_t, "cached": cached, "total": total}


def _judge_pass(last_message: str, task: ComparisonTask) -> bool | None:
    # TODO: wire an LLM-judge (reuse ee/hogai/eval/scorers) grading last_message against
    # task.expected_summary. Stubbed for the spike so we get tokens/outcome/time first.
    return None


async def _run_one(arm: Arm, task: ComparisonTask, rep: int, sandboxed_demo_data) -> RunResult:
    context = await asyncio.to_thread(sandboxed_demo_data.make_context, f"cmp-{arm.key}-{task.name}-{rep}")
    if arm.needs_steering:
        await asyncio.to_thread(_install_steering, context.team_id)

    case = SandboxedEvalCase(name=f"{arm.key}-{task.name}-{rep}", prompt=task.prompt)
    result = await run_eval_case(case, context)

    parsed = parse_log(result.raw_log, initial_prompt=task.prompt) if result.raw_log else None
    last_message = ""
    if parsed:
        for msg in reversed(parsed.messages):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
                last_message = " ".join(
                    b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text"
                )
                if last_message:
                    break

    tok = _tokens(result.raw_log, task.prompt)
    outcome = await asyncio.to_thread(task.outcome_check, context.team_id)
    return RunResult(
        arm=arm.label,
        task=task.name,
        rep=rep,
        total_tokens=tok["total"],
        input_tokens=tok["input"],
        output_tokens=tok["output"],
        cached_tokens=tok["cached"],
        duration_seconds=result.artifacts.duration_seconds,
        outcome_pass=outcome,
        judge_pass=_judge_pass(last_message, task),
        exit_code=result.artifacts.exit_code,
    )


async def eval_cli_vs_mcp(sandboxed_demo_data, mcp_mode, pytestconfig):
    """Benchmark entry point. Not an assertion test — it writes a report and never fails
    on scores (it's a measurement, not a gate). Named ``eval_*`` so the eval pytest.ini
    (python_files=eval_*.py, python_functions=eval_*) collects it."""
    # The autouse _apply_mcp_mode parametrizes this across modes; only run the benchmark
    # once. The per-arm loop sets the mode itself.
    if mcp_mode != "tools":
        pytest.skip("comparison runs once; the arm loop controls MCP mode")

    results: list[RunResult] = []
    for arm in ARMS:
        with _configure_arm(arm):
            for task in TASKS:
                for rep in range(REPS):
                    try:
                        results.append(await _run_one(arm, task, rep, sandboxed_demo_data))
                    except Exception:
                        logger.exception("Comparison run failed: arm=%s task=%s rep=%d", arm.key, task.name, rep)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "comparison.md").write_text(render_markdown(results))
    (OUT_DIR / "comparison.json").write_text(render_json(results))
    print(f"\n[comparison] wrote report to {OUT_DIR}/comparison.md\n")  # noqa: T201
    print(render_markdown(results))  # noqa: T201
