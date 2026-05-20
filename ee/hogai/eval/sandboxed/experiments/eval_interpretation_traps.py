"""Eval: agent handles two interpretation-trap shapes from diagnostic group C.

Carrier scenarios for diagnostic group C from
``products/experiments/skills/diagnosing-experiment-results/SKILL.md``.

Two cases:

1. ``low_volume_30_16_split`` (C2 — small-sample variance) — the user supplies
   the numbers in the prompt (46 total exposures, 30/16 split) and asks
   whether this is a real signal AND whether to ship the control variant.
   The skill body lists this exact example as a wait-don't-act case.
   Graded on two dimensions:
   - ``CitesDiagnosticGroup`` — did the agent identify the small-sample
     mechanism?
   - ``AdvisesAgainstShipping`` — did the agent translate that diagnosis
     into "don't ship yet" guidance? This catches the failure mode where
     the agent identifies the issue but still greenlights a ship.

2. ``early_significance_notification`` (C9 — significance reached early) —
   user reports PostHog flagging significance at low sample / short runtime
   and asks whether to ship. Correct behavior is to treat the notification
   as a *prompt to review*, not an instruction to ship — wait for the
   pre-planned duration or for the signal to stabilise. Same two-scorer
   shape as case 1.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_interpretation_traps.py \\
        -v --mcp-mode tools"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import AdvisesAgainstShipping, CitesDiagnosticGroup
from ee.hogai.eval.sandboxed.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


@pytest.mark.django_db
async def eval_interpretation_traps(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="low_volume_30_16_split",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' is configured as a 50/50 split, but I'm "
                "seeing a 30/16 split in actual exposures with only 46 total exposures so far. "
                "The control variant looks like it's winning. Is this a real signal or should I "
                "wait? Should I ship the control variant?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group tests identification of the small-sample mechanism.
                # advises_against_shipping tests behavioral translation into "don't ship".
                # Both are needed: the previous version of this case relied on diagnosis_group
                # alone, where the LLM judge's "must recommend waiting" criterion was bundled
                # into the diagnosis description — splitting them separates content from
                # behavior and makes regressions in either dimension visible independently.
                "diagnosis_group": (
                    "The agent identifies that 46 total exposures is too small a sample to draw "
                    "any conclusion — the observed 30/16 imbalance and the apparent winner are "
                    "both consistent with normal small-sample variance, not a real signal. The "
                    "skill's C2 (low-volume variance) diagnostic."
                ),
                "advises_against_shipping": True,
            },
        ),
        SandboxedEvalCase(
            # Inline-evidence pattern. The shape: PostHog flagged significance early, the user
            # reads "completed" as a green light and asks whether to ship. Correct behavior is
            # to treat the notification as a "prompt to review", not an instruction to ship —
            # wait for pre-planned duration, check guardrails, etc. The numbers (250/variant,
            # 36 hours) are chosen below the running-time-calculator threshold and well inside
            # the "early flips" noise band.
            name="early_significance_notification",
            prompt=(
                f"PostHog just notified me that my experiment '{ROLLOUT_EXPERIMENT_NAME}' has "
                "reached significance — the test variant is winning on the primary metric "
                "(signup conversion) with a chance-to-win of 96%. We have about 250 exposures "
                "per variant and the experiment has been running for 36 hours. Should I ship "
                "the test variant now?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group: agent must identify that early significance with small
                # sample / short runtime is the C9 trap — verdict can revert as sample grows.
                # advises_against_shipping: agent must not greenlight a ship on this evidence.
                "diagnosis_group": (
                    "The agent identifies that a 'significance reached' notification at low "
                    "sample (~250/variant) and short runtime (36 hours) is not a green light to "
                    "ship — early significance can flip back to non-significant as more data "
                    "arrives. The agent should reference the running-time calculator threshold, "
                    "the noise band on early flips, the pre-planned duration, or the C9 "
                    "diagnostic ('Significance reached notification is not a green light to "
                    "ship') in substance. An answer that takes the 96% chance-to-win at face "
                    "value without flagging the sample-size and runtime caveats fails."
                ),
                "advises_against_shipping": True,
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-diagnose-interpretation-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CitesDiagnosticGroup(),
            AdvisesAgainstShipping(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
