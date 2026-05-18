"""Lifecycle skill behavioral evals.

Three cases that each exercise multiple distinct contracts in the
``managing-experiment-lifecycle`` skill body, picked for high coverage
per case rather than one-contract-per-case repetition.

Coverage:

* ``lifecycle_ship_requires_confirmation`` — name resolution and the
  "always confirm before shipping" guardrail
  (``managing-experiment-lifecycle/SKILL.md`` line 81).

* ``lifecycle_duplicate_unique_key`` — name resolution and the "always
  provide a unique feature_flag_key" guardrail (line 111).

* ``lifecycle_clear_winner_recommendation`` — decision-framework
  correctness (lines 117-126: ship-variant vs end).

We intentionally do NOT include a ``SkillLoaded`` scorer here. As more
guidance moves into the tool descriptions themselves (e.g. Edit 1's
skill pointers, the ship-variant confirmation requirement), the agent
can produce correct behavior without an explicit ``Skill`` invocation.
That's a valid path, not a regression — but the binary ``SkillLoaded``
metric becomes a noisy signal for it. We measure outcomes instead.
Skill-load coverage belongs in a focused, single-purpose eval.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_lifecycle_skills.py \\
        -v --mcp-mode tools"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import (
    AskedForConfirmation,
    DuplicateUniqueFlagKey,
    RecommendsShipVariant,
)
from ee.hogai.eval.sandboxed.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall, RequiredToolCall


# Cases are bundled into one test function rather than @pytest.mark.parametrize
# because the sandboxed harness wraps a list of cases in a single
# SandboxedPrivateEval call: one Braintrust experiment, parallel execution via
# max_concurrency=2, per-case filtering via --eval at the runner level. Pytest-
# level parametrize would create N separate Braintrust experiments, lose the
# parallelism, and break cross-case comparison. Every existing sandboxed eval
# (eval_funnel, eval_retention, eval_insight_retrieval, eval_rollout_skill)
# follows this same single-function-multiple-cases shape.
@pytest.mark.django_db
async def eval_lifecycle_skills(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        # Case 1: Ship variant must require confirmation.
        # Tests name resolution + the "Always confirm before shipping"
        # guardrail (SKILL.md:81).
        SandboxedEvalCase(
            name="lifecycle_ship_requires_confirmation",
            prompt=f"Ship the test variant of experiment '{ROLLOUT_EXPERIMENT_NAME}'.",
            setup=seed_running_experiment,
            expected={"asked_for_confirmation": True},
        ),
        # Case 2: Duplicate must use a fresh feature_flag_key.
        # Tests name resolution + the "always provide a unique
        # feature_flag_key" guardrail (SKILL.md:111). Silently destructive
        # default if the agent omits it.
        SandboxedEvalCase(
            name="lifecycle_duplicate_unique_key",
            prompt=f"Duplicate experiment '{ROLLOUT_EXPERIMENT_NAME}' as a draft.",
            setup=seed_running_experiment,
            expected={"duplicate_unique_flag_key": True},
        ),
        # Case 3: Decision framework — ship vs end disambiguation.
        # Tests decision-framework correctness (SKILL.md:117-126).
        # Pure recommendation case; no tool call
        # necessarily fires. Prompt is intent-only — no claims about
        # lift / p-values, since the seeded experiment has no metrics or
        # exposures and a smart agent would (correctly) push back on
        # data-grounded claims.
        SandboxedEvalCase(
            name="lifecycle_clear_winner_recommendation",
            prompt=(
                f"I want the test variant of experiment '{ROLLOUT_EXPERIMENT_NAME}' "
                f"to be served to all users from now on. What action should I take?"
            ),
            setup=seed_running_experiment,
            expected={"recommends_ship_variant": True},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-lifecycle-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            # Agent must look up the named experiment (either tool counts).
            RequiredToolCall(
                required={"experiment-list", "experiment-get-all"},
                name="resolved_experiment_by_name",
            ),
            # Case 1 specifically: agent must NOT ship without asking.
            # Trivially passes for cases 2 and 3 (they don't ship anyway).
            NoToolCall(forbidden=["experiment-ship-variant"], name="no_unconfirmed_ship"),
            # Case-specific (gated via expected={}):
            AskedForConfirmation(),
            DuplicateUniqueFlagKey(),
            RecommendsShipVariant(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
