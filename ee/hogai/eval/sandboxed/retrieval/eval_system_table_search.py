"""System-table search eval for the sandboxed product-analytics agent.

When users ask the agent to find or modify a PostHog entity by name
(e.g. "rename the MAU insight"), the agent reaches for ``execute-sql``
against ``system.*``. The failure mode this eval grades: the agent
guesses column names (``last_modified_at``, ``description``,
``short_id``) without calling ``read-data-warehouse-schema`` first.
Different ``system.*`` tables expose different columns, so guessing
produces queries that fail or silently return wrong rows.

Single metric:

* ``warehouse_schema_before_sql`` — was every successful ``execute-sql``
  preceded by a successful ``read-data-warehouse-schema`` in the same
  run? Mode-agnostic (works for both v2 tools mode and CLI exec mode).

To run::

    pytest ee/hogai/eval/sandboxed/retrieval/eval_system_table_search.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.retrieval.scorers import WarehouseSchemaBeforeSql
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


@pytest.mark.django_db
async def eval_system_table_search(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="system_table_search_insights_rename",
            prompt="rename the MAU insight to have a single 'MAU - ' prefix",
            expected={"warehouse_schema_before_sql": {}},
        ),
        SandboxedEvalCase(
            name="system_table_search_insights_find",
            prompt=(
                "find me a graph of MAUs using the app. "
                "it's probably an existing insight, and created/last used by "
                "me around this time last year."
            ),
            expected={"warehouse_schema_before_sql": {}},
        ),
        SandboxedEvalCase(
            name="system_table_search_insights_list_revenue",
            prompt=(
                "do we have any insights tracking revenue or payments? "
                "list every match with its ID, name, and last-modified time."
            ),
            expected={"warehouse_schema_before_sql": {}},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-system-table-search-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            WarehouseSchemaBeforeSql(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
