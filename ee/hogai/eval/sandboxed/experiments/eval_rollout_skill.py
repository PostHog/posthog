"""Skill-load eval for ``configuring-experiment-rollout``.

Asks the agent to change the variant split on a running experiment from
50/50 to 70/30 and grades whether the ``configuring-experiment-rollout``
skill auto-loaded before the agent took action. Single deterministic
scorer (``SkillLoaded``) — no LLM judge — so the signal is binary and
cheap to reproduce while iterating on the skill's description.

Maps to stress-test finding #7 (skills rarely auto-load), specifically
the variant-split rows (2.5, 5.3, 5.4, 5.5) in STEP_1_HARNESS.md. Uses
``SandboxedPrivateEval`` so it runs without a Braintrust API key —
local logs and PostHog ``$ai_trace`` events still emit.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_rollout_skill.py \\
        -v --mcp-mode tools --eval rollout"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment
from ee.hogai.eval.sandboxed.retrieval.scorers import SkillLoaded
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero

SKILL_NAME = "configuring-experiment-rollout"


@pytest.mark.django_db
async def eval_rollout_skill(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="rollout_change_split_70_30",
            prompt=(
                f"Change the variant split on the running experiment '{ROLLOUT_EXPERIMENT_NAME}' from 50/50 to 70/30."
            ),
            setup=seed_running_experiment,
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-rollout-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            SkillLoaded(skill_name=SKILL_NAME),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
