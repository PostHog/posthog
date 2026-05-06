"""HogQL feature-regression pins.

A growing file of *one case per recently-fixed HogQL behaviour*, kept so
silent regressions get caught the next time a query parser, printer, or
MCP-layer fix lands.

Each case should be cheap (single ``execute-sql`` call), exercise the
exact feature that was fixed, and assert on a deterministic outcome via
``HogQLOutputMatches``. Adding a new pin: drop another
``SandboxedEvalCase`` with a prompt that *only* succeeds if the fixed
behaviour holds, and a tight ``expected`` bound. Reference the fix PR
in a comment so future-readers know what each pin protects.

The two cases below are bootstrap structure — generic HogQL features
that every fix touches in some form — not specific known regressions.
Replace them as concrete fixes land that we want to lock in.

To run:
    pytest ee/hogai/eval/sandboxed/data_warehouse/eval_sql_regressions.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.data_warehouse.scorers import HogQLOutputMatches
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, RequiredToolCall


@pytest.mark.django_db
async def eval_sql_regressions(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        SandboxedEvalCase(
            name="regression_time_window_filter",
            # Exercises HogQL's date arithmetic + relative-time filtering.
            # If the parser regresses on `now() - INTERVAL` or `dateDiff`,
            # this case starts returning 0 or erroring.
            prompt=("How many $pageview events happened in the last 90 days? Just give me the count."),
            expected={
                "hogql_output_matches": {"non_zero": True},
            },
        ),
        SandboxedEvalCase(
            name="regression_subquery_in_filter",
            # Exercises subquery + IN — a shape MCP-driven agents hit a
            # lot when chaining "find users matching X, then count their
            # events". Regressions in subquery scoping or correlated
            # subquery handling fail this case loudly.
            prompt=(
                "Count $pageview events from users (distinct_id) who also "
                "have at least one event with event = '$autocapture'. "
                "Just give me the number."
            ),
            expected={
                "hogql_output_matches": {"non_zero": True},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-sql-regressions-{mcp_mode}",
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
