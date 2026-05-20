"""Eval: agent handles mid-run / lifecycle scenarios across two carrier shapes.

Carrier scenarios for diagnostic group E from
``products/experiments/skills/diagnosing-experiment-results/SKILL.md``.

Two cases:

1. ``ship_variant_flag_flip_on_stopped_experiment`` (E7 — post-hoc) — the
   seeded experiment is *stopped* and its feature flag has been rewritten by
   ``experiment-ship-variant``; multivariate is now 0/100, and the verbatim
   E7 signature ("Added automatically when the experiment was ended to keep
   only one variant.") sits in the activity log. Tests two behaviors: the
   agent names the ship-variant flip as the cause AND does not push reversal
   on a stopped experiment (Step 4 state-aware rule).

2. ``ship_variant_under_uncertainty`` (E5 / C10 — pre-ship guidance) — a
   *running* experiment, primary metric up but a secondary / guardrail metric
   trending negative. The user asks whether to ship the test variant. The
   correct behavior is to advise AGAINST a confident ship — flagging the
   guardrail, recommending more data or holding to control, and warning
   about the ship-variant release-mode choice (PR #58828 introduced
   "experiment population" vs "all users" — uncertain ships should not pick
   "all users"). This case tests the agent's pre-ship judgment, which the
   existing E7 post-hoc case does not exercise.

The seeder writes a real ``ActivityLog`` row carrying the synthetic 50/50 →
0/100 diff (with the verbatim "Added automatically when the experiment was
ended to keep only one variant." signature in
``detail.changes[].after.groups[].properties[].description``) so that any
investigation path the agent picks — reading the live flag config,
inspecting the activity log, or replaying experiment-stats — surfaces real
production-shaped state. Which path the agent takes is not graded; only the
final diagnosis and the no-edit recommendation are.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_midrun_changes.py \\
        -v --mcp-mode tools"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import (
    AdvisesAgainstShipping,
    CitesDiagnosticGroup,
    DoesNotRecommendEdit,
)
from ee.hogai.eval.sandboxed.experiments.seeders import (
    ENDED_EXPERIMENT_NAME,
    ROLLOUT_EXPERIMENT_NAME,
    seed_ended_experiment_with_flag_flip,
    seed_running_experiment,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


@pytest.mark.django_db
async def eval_midrun_changes(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="ship_variant_flag_flip_on_stopped_experiment",
            prompt=(
                # Neutral framing — no "unexpectedly", no "by accident", no hint of remorse.
                # The user is asking what happened, not asking to undo it. The state-aware
                # rule (Step 4) requires the agent to explain only, not offer reversal
                # mechanics unprompted.
                f"My experiment '{ENDED_EXPERIMENT_NAME}' has ended. The feature flag is now rolling "
                "out the test variant to 100% of users, but I had it set up as a 50/50 split. "
                "Why is the flag distribution different from what I configured?"
            ),
            setup=seed_ended_experiment_with_flag_flip,
            expected={
                "diagnosis_group": (
                    "The flag was rewritten when the experiment was ended via ship-variant — PostHog "
                    "rewrites the multivariate distribution to 0/100 in favour of the shipped variant "
                    "and adds a property entry with the description "
                    "'Added automatically when the experiment was ended to keep only one variant.'. "
                    "This is the documented behavior of ship-variant, not an error."
                ),
                "does_not_recommend_edit": True,
            },
        ),
        SandboxedEvalCase(
            # Pre-ship judgment under conflicting metrics. Tests C10's "default to control
            # on ambiguous ships" rule and E7's release-mode caution. The user explicitly
            # asks "should I ship?" — the correct answer is "not yet / not on this evidence",
            # not "ship the test variant because the primary is up".
            name="ship_variant_under_uncertainty",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' has been running 10 days. The primary "
                "metric (signup conversion) is up about 8% in the test variant with a chance-to-win "
                "around 94%. But my guardrail secondary metric (7-day retention) is down about 3% "
                "in the test variant. Should I ship the test variant? And if so, should I roll it "
                "out to all users or just keep it scoped to the experiment population?"
            ),
            setup=seed_running_experiment,
            expected={
                # diagnosis_group tests identification only: did the agent name the
                # ship-variant default risk, guardrail vs primary tension, and release-mode
                # choice? Behavioral grading ("must not greenlight a ship") lives in
                # advises_against_shipping. Splitting them mirrors eval_interpretation_traps.py
                # — content and behavior regress on different axes and should be measured
                # independently.
                "diagnosis_group": (
                    "The agent identifies at least one of these as the relevant diagnostic: "
                    "(a) the guardrail / secondary metric trending negative is the gap the "
                    "ship-variant recommendation logic does NOT consider — guardrail-aware "
                    "users are the ones the default would mislead, (b) the primary's "
                    "chance-to-win is in the noise band where early flips happen, so the "
                    "significance is not settled, (c) on ambiguous ships the safe default is "
                    "to keep control rather than ship the position-default test variant. If "
                    "release mode is discussed, the agent should prefer 'experiment "
                    "population' (default) over 'all users' — uncertain ships should not "
                    "extend the blast radius past the experiment's existing population."
                ),
                "advises_against_shipping": True,
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-diagnose-midrun-changes-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CitesDiagnosticGroup(),
            DoesNotRecommendEdit(),
            AdvisesAgainstShipping(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
