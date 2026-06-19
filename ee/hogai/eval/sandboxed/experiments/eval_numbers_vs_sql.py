"""Eval: agent handles PostHog-vs-SQL divergence in two shapes — scope mismatch and anti-routing.

Carrier scenarios for diagnostic group D from
``products/experiments/skills/diagnosing-experiment-results/SKILL.md``.

Two cases:

1. ``posthog_count_below_raw_sql`` — the user's hand-written SQL counts more
   events than PostHog's experiment view. The skill lists the canonical
   reasons (exposure scope, ``$multiple`` exclusion, test-account filter,
   date range) — agent should name at least one without treating SQL as
   ground truth.

2. ``exposures_vastly_exceed_metric`` — exposures sit at ~11k but the
   primary metric only counts ~110 events (a ~100× gap). Presents as a
   group-D scope mismatch but the root cause is identity / bucketing
   (group A — A3 fragmentation, A4 bootstrap × ``/decide``, or A6/A8
   identifier migration). The skill's dispatch table for this symptom
   explicitly says "route here before D" — this case tests whether the
   agent obeys that routing rule under surface pressure (it looks like a
   D problem) rather than just reciting it. Uses the inline-evidence
   pattern from ``srm_with_identity_fragmentation``: the prompt carries the
   bucketing signatures (`$multiple` share, distinct_id/person ratio) so
   the agent has the diagnostic evidence without needing seeded state to
   match.

To run:

    flox activate -- bash -c "set -a; source .env; set +a; \\
        pytest -c ee/hogai/eval/pytest.ini \\
        ee/hogai/eval/sandboxed/experiments/eval_numbers_vs_sql.py \\
        -v --mcp-mode tools"
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.experiments.scorers import CitesDiagnosticGroup
from ee.hogai.eval.sandboxed.experiments.seeders import ROLLOUT_EXPERIMENT_NAME, seed_running_experiment
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


@pytest.mark.django_db
async def eval_numbers_vs_sql(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="posthog_count_below_raw_sql",
            prompt=(
                f"My experiment '{ROLLOUT_EXPERIMENT_NAME}' shows about 500 users in the metric on the "
                "experiment page, but when I run my own SQL (`SELECT count(DISTINCT person_id) FROM "
                "events WHERE event = '$pageview' AND timestamp >= <start_date>`) I get 1000. PostHog "
                "seems to be missing half my users. Which number is right and why don't they match?"
            ),
            setup=seed_running_experiment,
            expected={
                # Broadened from "must be the primary focus" to "must be named somewhere in the
                # response": the agent's correct enumeration behavior (anti-bundle rule) means it
                # may surface auxiliary findings alongside the D-group diagnostic — e.g. if the
                # seeded project shows the flag isn't being called at all, the agent will (rightly)
                # surface that as a B-group finding. The skill's anti-bundle rule explicitly wants
                # multiple findings surfaced; this scorer should not penalize that.
                "diagnosis_group": (
                    "The agent names AT LEAST ONE of the scope filters that the PostHog experiment "
                    "view applies but raw SQL does not replicate — any of: (a) the test-account "
                    "filter (excluded by default), (b) the $multiple variant exclusion, (c) the "
                    "exposure-event scope (the experiment counts users who fired "
                    "$feature_flag_called, not arbitrary pageview users), or (d) the experiment's "
                    "date range. The agent must also frame the gap as 'PostHog and raw SQL measure "
                    "different populations' — i.e. PostHog's number is not wrong, the SQL is "
                    "missing scope filters. Surfacing the scope-filter mechanism ALONGSIDE other "
                    "findings (e.g. that the flag may not actually be called) qualifies; the "
                    "scope-filter explanation does not need to be the response's primary focus, "
                    "only present and substantively named."
                ),
            },
        ),
        SandboxedEvalCase(
            # Anti-routing test. Symptom looks like a D problem ("numbers don't match") but
            # the magnitude (two orders of magnitude gap between exposures and the metric)
            # is the signature of identity / bucketing failure, not scope reconciliation.
            # The skill's dispatch table for this exact shape says "route here before D" —
            # this case verifies the agent obeys the dispatch rule under the temptation of
            # the surface symptom.
            #
            # Inline-evidence pattern: the prompt itself carries the bucketing signatures
            # ($multiple share, distinct_id/person ratio) so the agent has everything needed
            # to route to A without verifying against project state.
            name="exposures_vastly_exceed_metric",
            prompt=(
                f"On my experiment '{ROLLOUT_EXPERIMENT_NAME}' I'm seeing something that looks "
                "like the numbers don't line up. Three observations:\n\n"
                "1. Exposures tab says about 11,000 users were exposed.\n\n"
                "2. The primary metric only counts about 110 events total — a 100× gap.\n\n"
                "3. When I drill into the raw exposure events, ~8% of them carry `$multiple` as "
                "the variant value, and the ratio of distinct distinct_ids per person_id is "
                "about 2× higher than I'd expect — many people seem to have multiple distinct "
                "IDs attached.\n\n"
                "The metric event scoping looks correct in the experiment page configuration. "
                "Where should I look first?"
            ),
            setup=seed_running_experiment,
            expected={
                # The skill's dispatch table maps "metric count is much smaller than exposures
                # (10× / 100× gap)" to group A first, not group D. With $multiple share and
                # distinct_id/person ratio both elevated in the prompt, the agent has decisive
                # inline evidence pointing at bucketing — there is no defensible reason to lead
                # with D scope filters.
                "diagnosis_group": (
                    "The agent identifies this is a bucketing / identity-resolution problem "
                    "(group A — A3 identity fragmentation, A4 bootstrap × /decide mismatch, or "
                    "A6/A8 identifier strategy change), NOT primarily a SQL scope mismatch "
                    "(group D). The inline evidence pins this: the elevated $multiple share "
                    "(~8%) plus the >1 distinct_ids/person ratio (~2×) are direct signatures of "
                    "identity fragmentation. The agent's response must lead with the identity / "
                    "bucketing route. An answer that leads with D scope filters (test-account "
                    "filter, $multiple exclusion as a scope filter, date range, conversion "
                    "window, etc.) without recognizing that the inline-reported $multiple and "
                    "distinct_id signals indicate a real bucketing problem fails — that is the "
                    "exact 'route here before D' miss the dispatch rule is designed to prevent."
                ),
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name=f"sandboxed-experiments-diagnose-numbers-vs-sql-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            CitesDiagnosticGroup(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
