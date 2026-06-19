"""Eval: agent diagnoses Group A bias mechanisms and surfaces co-occurring findings independently.

Carrier scenarios for diagnostic group A from
``products/experiments/skills/diagnosing-experiment-results/SKILL.md``.

Two cases:

1. ``uneven_split_alone`` — user reports the smaller variant looks biased on
   an 80/20 split with no other evidence. Agent should enumerate plausible
   mechanisms (variance, power, SRM, Exclude, selection skew) rather than
   commit to one without data.

2. ``srm_with_identity_fragmentation`` — anti-bundle test. User reports two
   distinct observations *inline* in their prompt: (a) configured 50/50 but
   actual exposure ratio is 51.2/48.8 at n=10,000 (chi-squared signature
   for SRM, A2), AND (b) distinct_id/person ratio is 1.5× (identity
   fragmentation signature, A3). Both mechanisms are evidence-grounded by
   the user's own report — no need for `experiment-get` to verify. The
   ``SurfacesAllFindings`` scorer fails the case if the agent collapses
   both observations into a single conclusion or names only one.

   This shape (evidence inline in the user's report) is the clean
   anti-bundle test — distinct from case 1 which is open-ended enumeration.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_bias_uneven_split.py \\
        -v --mcp-mode tools"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import CitesDiagnosticGroup, SurfacesAllFindings
from ee.hogai.eval.sandboxed.experiments.seeders import (
    ROLLOUT_EXPERIMENT_NAME,
    UNEVEN_SPLIT_EXPERIMENT_NAME,
    seed_running_experiment,
    seed_uneven_split_experiment,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


@pytest.mark.django_db
async def eval_bias_uneven_split(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="uneven_split_alone",
            prompt=(
                f"My experiment '{UNEVEN_SPLIT_EXPERIMENT_NAME}' has a smaller variant that looks biased — "
                "conversion in the test variant is way higher than in control. Why might this be?"
            ),
            setup=seed_uneven_split_experiment,
            expected={
                # With no data attached to the user's prompt, the right behavior is to
                # enumerate plausible mechanisms, not to pick one. Insisting on a single
                # mechanism (e.g. A1 / Exclude bias) would overfit the eval — the agent
                # genuinely cannot know which mechanism is active without snapshot data.
                # Pass if at least two distinct mechanisms are surfaced from the canonical set.
                "diagnosis_group": (
                    "The agent enumerates AT LEAST TWO distinct plausible mechanisms from this set: "
                    "(1) small-sample variance / wider confidence interval on the smaller arm, "
                    "(2) reduced statistical power from the uneven split, "
                    "(3) sample-ratio mismatch (SRM) — the actual exposure ratio drifts from 80/20, "
                    '(4) uneven-split + multiple_variant_handling="exclude" bias — overlap users '
                    "are asymmetrically pruned from the smaller arm, "
                    "(5) selection / cohort skew in a small bucket. "
                    "Any 2+ qualifies. Picking only one (e.g. just naming small-sample variance) "
                    "does NOT qualify — the anti-bundle rule requires surfacing the full plausible "
                    "set when evidence does not narrow to one cause."
                ),
            },
        ),
        SandboxedEvalCase(
            # Anti-bundle test, replacing the previous "uneven_split_with_low_volume" case.
            # Both mechanisms (SRM + identity fragmentation) are evidence-grounded by the
            # user's own report inline — the agent doesn't need `experiment-get` to verify
            # either one. The clean test of the anti-bundle rule: when two distinct
            # observations are presented, the agent must surface both, not collapse to one.
            name="srm_with_identity_fragmentation",
            prompt=(
                f"Looking at my experiment '{ROLLOUT_EXPERIMENT_NAME}'. Configured as a 50/50 split, "
                "but I've noticed two things and I'm not sure if they're related:\n\n"
                "1. The actual exposure ratio in the data is 51.2/48.8 across about 10,000 exposures "
                "— close to 50/50 but not exact.\n\n"
                "2. My `distinct_id` / `person_id` ratio is about 1.5× — some users seem to have "
                "multiple distinct IDs attached to them.\n\n"
                "What's going on here? Should I be worried?"
            ),
            setup=seed_running_experiment,
            expected={
                "surfaces_all_findings": [
                    (
                        "Sample ratio mismatch (SRM) — the configured 50/50 split vs the observed "
                        "51.2/48.8 at n=10,000 fails the chi-squared check for randomness, "
                        "indicating a real assignment or capture problem (not just noise)."
                    ),
                    (
                        "Identity fragmentation — a distinct_id/person ratio of 1.5× means users are "
                        "being split across multiple distinct IDs (likely from `identify()` timing, "
                        "cross-device usage, or an anonymous-to-identified transition), which "
                        "asymmetrically affects variant assignment."
                    ),
                ],
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-diagnose-bias-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CitesDiagnosticGroup(),
            SurfacesAllFindings(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
