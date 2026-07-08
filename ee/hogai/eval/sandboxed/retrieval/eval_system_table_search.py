"""System-table search eval for the sandboxed product-analytics agent.

When users ask the agent to find or modify a PostHog entity by name
(e.g. "rename the MAU insight"), the agent reaches for ``execute-sql``
against ``system.*``. The failure modes this eval grades:

1. The agent guesses column names (``last_modified_at``, ``description``,
   ``short_id``) without discovering the schema via
   ``system.information_schema`` first. Different ``system.*`` tables
   expose different columns, so guessing produces queries that fail or
   silently return wrong rows.
2. In single-exec CLI mode, the agent invokes a tool without first
   loading its schema via ``info <tool>`` — skipping the discovery step
   that surfaces parameter shapes and discovery workflows.

Metrics:

* ``information_schema_before_sql`` — was every ``execute-sql`` against a
  ``system.*`` entity table preceded by a ``system.information_schema``
  discovery query in the same run? Mode-agnostic (works for both v2 tools
  mode and CLI exec mode).
* ``info_before_execute_sql`` — CLI-mode only: was ``execute-sql``'s
  ``info`` payload loaded before its first successful ``call``? Skipped
  (``None``) in v2 tools mode where schemas come bundled.

To run::

    pytest ee/hogai/eval/sandboxed/retrieval/eval_system_table_search.py
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.retrieval.scorers import InfoCalledBeforeTool, InformationSchemaBeforeSql
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero
from ee.hogai.eval.sandboxed.seeders.insight import seed_insight_noise


async def eval_system_table_search(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    # ``seed_insight_noise`` adds ~1000 plausible-looking noise insights plus a
    # handful of deterministic lookup insights (incl. "Monthly Active Users
    # (Hedgebox)") to the per-case team. The noise volume makes `insights-list`
    # pagination painful and pushes the agent toward `execute-sql` against
    # `system.insights` — which is what the schema-discipline scorers grade.
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="system_table_search_insights_rename",
            prompt=("rename the insight 'Monthly Active Users (Hedgebox)' to have a 'MAU - ' prefix"),
            expected={"information_schema_before_sql": {}},
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="system_table_search_insights_find",
            prompt=(
                "find me a graph of MAUs using the app. "
                "it's probably an existing insight, and created/last used by "
                "me around this time last year."
            ),
            expected={"information_schema_before_sql": {}},
            setup=seed_insight_noise,
        ),
        SandboxedEvalCase(
            name="system_table_search_insights_list_revenue",
            prompt=(
                "do we have any insights tracking revenue or payments? "
                "list every match with its ID, name, and last-modified time."
            ),
            expected={"information_schema_before_sql": {}},
            setup=seed_insight_noise,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-system-table-search-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaBeforeSql(),
            InfoCalledBeforeTool("execute-sql"),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
