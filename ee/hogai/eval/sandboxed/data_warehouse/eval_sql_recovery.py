"""SQL-recovery evals for the sandboxed data-warehouse agent.

These cases give the agent a query that *will* fail at parse or execution
time and grade whether it recovers — fixes the query and re-runs via
``execute-sql`` — without the user having to nudge it.

Recovery is the complement to skoob13's ``eval_verify_event_before_query``
in ``cli_mcp/eval_workflow.py``: that suite asks "did the agent verify
schema *before* querying?", we ask "did the agent recover *after* a query
broke?". Both signals are useful; an agent that always pre-verifies is
safe but slow, an agent that recovers cleanly is robust under real-world
typos and stale schema.

Scoring stack per case:

- ``ExitCodeZero`` — the agent process finished cleanly.
- ``RequiredToolCall(["execute-sql"])`` — at least one *successful*
  ``execute-sql`` call appears (the recovery actually ran).
- ``HogQLOutputMatches`` — the fixed query returned a number consistent
  with the demo data. The bound is loose (``non_zero`` or wide range)
  because we care that recovery happened at all, not the precise count;
  ``eval_sql_correctness`` is where exact answers live.

To run:
    pytest ee/hogai/eval/sandboxed/data_warehouse/eval_sql_recovery.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.data_warehouse.scorers import HogQLOutputMatches
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, RequiredToolCall


@pytest.mark.django_db
async def eval_sql_recovery(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        SandboxedEvalCase(
            name="recovery_misspelled_column",
            # `evnt` instead of `event`. HogQL surfaces an unknown-column
            # error; agent should consult the schema (or implicit
            # knowledge) and rerun against the right column.
            prompt=("Run this query and tell me the result:\n\nSELECT count() FROM events WHERE evnt = '$pageview'"),
            expected={
                "hogql_output_matches": {"non_zero": True},
            },
        ),
        SandboxedEvalCase(
            name="recovery_wrong_function_case",
            # ClickHouse function names are case-sensitive — `DATEDIFF`
            # doesn't exist, the agent should reach for `dateDiff`.
            prompt=(
                "Use this query as a starting point and tell me how many distinct days "
                "had pageview events:\n\n"
                "SELECT DATEDIFF('day', min(timestamp), max(timestamp)) "
                "FROM events WHERE event = '$pageview'"
            ),
            expected={
                "hogql_output_matches": {"non_zero": True},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-sql-recovery-{mcp_mode}",
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
