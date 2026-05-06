"""SQL-correctness evals for the sandboxed data-warehouse agent.

These cases ask the agent to compute something whose answer is determined
by the Hedgebox demo seed and grade whether the number it surfaces is
right. They are the layer underneath skoob13's workflow scorers in
``cli_mcp/eval_workflow.py`` — those grade *which tools* the agent
called; we grade *what the result was*.

The expected values are bounded ranges, not exact numbers, because the
Hedgebox seed includes randomised simulation steps and the absolute
counts shift run-over-run. Ranges should be wide enough to absorb that
randomness but tight enough that wrong queries (off-by-orders-of-magnitude
errors, wrong filters, missing GROUP BY) fail. See ``README.md`` in this
folder for how to calibrate the ranges against a real seed.

Scoring stack per case:

- ``ExitCodeZero`` — agent finished cleanly.
- ``RequiredToolCall(["execute-sql"])`` — at least one successful
  ``execute-sql`` call.
- ``HogQLOutputMatches`` — the answer falls in the expected range.

To run:
    pytest ee/hogai/eval/sandboxed/data_warehouse/eval_sql_correctness.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.data_warehouse.scorers import HogQLOutputMatches
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, RequiredToolCall


@pytest.mark.django_db
async def eval_sql_correctness(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        SandboxedEvalCase(
            name="correctness_total_pageviews",
            prompt="How many $pageview events are there in total? Just give me the count.",
            # Wide range — the absolute number drifts with each Hedgebox
            # seed run, but it's reliably in the thousands.
            expected={
                "hogql_output_matches": {"min": 100, "max": 1_000_000},
            },
        ),
        SandboxedEvalCase(
            name="correctness_distinct_users",
            prompt="How many distinct users (distinct_id) have a $pageview event?",
            expected={
                "hogql_output_matches": {"min": 10, "max": 100_000},
            },
        ),
        SandboxedEvalCase(
            name="correctness_filtered_count",
            prompt=("Count the number of $pageview events on the URL https://hedgebox.net/. Just give me the number."),
            expected={
                "hogql_output_matches": {"min": 10, "max": 1_000_000},
            },
        ),
        SandboxedEvalCase(
            name="correctness_group_by_top_event",
            # The agent has to GROUP BY event and identify the top one.
            # Hedgebox is a $pageview-heavy app so $pageview should win.
            prompt=("Which single event name has the most occurrences? Just tell me the event name."),
            expected={
                "hogql_output_matches": {"regex": r"\$pageview"},
            },
        ),
        SandboxedEvalCase(
            name="correctness_join_persons",
            # Forces a join from events to persons (or person properties).
            # The agent has to know the right shape — we don't grade the
            # exact number, only that something non-zero comes back.
            prompt=(
                "How many distinct users have a $pageview event AND have an email address set on their person profile?"
            ),
            expected={
                "hogql_output_matches": {"non_zero": True},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-sql-correctness-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            RequiredToolCall(["execute-sql"], name="execute_sql_succeeded"),
            HogQLOutputMatches(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
