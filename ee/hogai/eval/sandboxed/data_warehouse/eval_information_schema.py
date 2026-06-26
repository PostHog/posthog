"""Data-warehouse ``information_schema`` navigation eval for the sandboxed agent.

Seeds a per-case team with hundreds of synthetic warehouse tables, data-modeling
views, and join relationships (``seed_warehouse_schema``), then grades whether the
agent uses ``system.information_schema`` to navigate the catalog at scale. The
``mcp-sql-schema-discovery`` flag is forced on in the harness, so discovery runs
through ``execute-sql`` against ``system.information_schema.*`` rather than a
dedicated schema tool.

Capabilities graded (one or more cases each):

1. **discover** the right tables/models,
2. **retrieve a lookup needle** with a real SQL query,
3. **agentic search** — filter by name/description/data_type/metadata instead of
   dumping the whole catalog,
4. **relationships + duck typing** — follow joins surfaced in
   ``information_schema.relationships``, and see through columns declared ``String``
   whose content is actually numeric/JSON.

Prompts read like real user questions and never mention ``information_schema``.

To run::

    pytest ee/hogai/eval/sandboxed/data_warehouse/eval_information_schema.py
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.data_warehouse.scorers import (
    AgenticSearchUsed,
    AnswerQueryRanWhenExpected,
    InformationSchemaBeforeAnswer,
    InformationSchemaQueried,
    NeedleTableIdentified,
    NeedleValueRetrieved,
    RelationshipDiscovery,
    WarehouseAnswerCorrectness,
)
from ee.hogai.eval.sandboxed.data_warehouse.seeder import seed_warehouse_schema
from ee.hogai.eval.sandboxed.data_warehouse.synthesizer import (
    DESC_NEEDLE_TABLE,
    REL_NEEDLE_KEY,
    REL_NEEDLE_SOURCE,
    REL_NEEDLE_TARGET,
    RETRIEVAL_NEEDLE_ANSWER,
    RETRIEVAL_NEEDLE_EVENT_ID,
    RETRIEVAL_NEEDLE_TABLE,
    TYPE_NEEDLE_TABLE,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


async def eval_information_schema(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases: list[SandboxedEvalCase] = [
        # 1 — discover the relevant tables/models for a topic.
        SandboxedEvalCase(
            name="dw_discover_models_for_topic",
            prompt=(
                "We sync a lot into our data warehouse. Which tables and data models do we have "
                "related to billing and subscriptions? Just list their names."
            ),
            expected={"information_schema_queried": {}, "agentic_search_used": {}},
            setup=seed_warehouse_schema,
        ),
        # 2 — identify a specific needle table by topic (no row query needed).
        SandboxedEvalCase(
            name="dw_needle_table_by_topic",
            prompt="Which warehouse table is the canonical source of truth for MRR?",
            expected={
                "information_schema_queried": {},
                "agentic_search_used": {},
                "needle_table_identified": {"table": DESC_NEEDLE_TABLE},
            },
            setup=seed_warehouse_schema,
        ),
        # 3 — value lookup against the queryable needle.
        SandboxedEvalCase(
            name="dw_needle_value_lookup",
            prompt=(
                f"In the warehouse table holding raw Stripe events, the row with "
                f"event_id '{RETRIEVAL_NEEDLE_EVENT_ID}' has a JSON payload stored as text. "
                f"What is its secret_code?"
            ),
            expected={
                "information_schema_before_answer": {},
                "answer_query_ran": {},
                "needle_value_retrieved": {},
                "warehouse_answer_correctness": {
                    "expected_answer": (
                        f"The secret_code in the payload of row {RETRIEVAL_NEEDLE_EVENT_ID} in "
                        f"{RETRIEVAL_NEEDLE_TABLE} is {RETRIEVAL_NEEDLE_ANSWER}."
                    ),
                    "requires_queryable": True,
                },
            },
            setup=seed_warehouse_schema,
        ),
        # 4 — search by description text.
        SandboxedEvalCase(
            name="dw_search_by_description",
            prompt=(
                "We have hundreds of warehouse tables. Find the one whose documentation says it's "
                "the canonical source for monthly recurring revenue, and tell me what it tracks."
            ),
            expected={
                "information_schema_queried": {},
                "agentic_search_used": {"require_pattern": True},
                "needle_table_identified": {"table": DESC_NEEDLE_TABLE},
            },
            setup=seed_warehouse_schema,
        ),
        # 5 — search by column data_type (an equality filter, not a text pattern).
        SandboxedEvalCase(
            name="dw_search_by_column_type",
            prompt=(
                "Across all our warehouse tables, which one has a column stored as a high-precision "
                "Decimal type (not a plain Float)? Give the table and column name."
            ),
            expected={
                "information_schema_queried": {},
                "agentic_search_used": {},
                "needle_table_identified": {"table": TYPE_NEEDLE_TABLE},
            },
            setup=seed_warehouse_schema,
        ),
        # 6 — relationship / join traversal.
        SandboxedEvalCase(
            name="dw_relationship_traversal",
            prompt=(
                f"Our orders table '{REL_NEEDLE_SOURCE}' is linked to another warehouse table "
                f"through a defined relationship. Which table is it, and on what key do they join?"
            ),
            expected={
                "information_schema_queried": {},
                "relationship_discovery": {},
                "warehouse_answer_correctness": {
                    "expected_answer": (f"{REL_NEEDLE_SOURCE} joins {REL_NEEDLE_TARGET} on the {REL_NEEDLE_KEY} key."),
                },
            },
            setup=seed_warehouse_schema,
        ),
        # 7 — duck typing: declared String, content is numeric/JSON.
        SandboxedEvalCase(
            name="dw_duck_typing_amount",
            prompt=(
                f"The 'amount' column in our '{RETRIEVAL_NEEDLE_TABLE}' table is stored as text. "
                "What is the largest amount value in that table, and is it actually numeric?"
            ),
            expected={
                "information_schema_queried": {},
                "needle_value_retrieved": {"value": "24990"},
                "warehouse_answer_correctness": {
                    "expected_answer": (
                        f"The largest amount in {RETRIEVAL_NEEDLE_TABLE} is 24990; the column is "
                        "declared as String/text but the values are numeric and must be cast to compare "
                        "(a plain text/string max would wrongly return 9990)."
                    ),
                    "requires_queryable": True,
                },
            },
            setup=seed_warehouse_schema,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-warehouse-info-schema-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaQueried(),
            InformationSchemaBeforeAnswer(),
            AgenticSearchUsed(),
            NeedleTableIdentified(),
            NeedleValueRetrieved(),
            RelationshipDiscovery(),
            AnswerQueryRanWhenExpected(name="answer_query_ran"),
            WarehouseAnswerCorrectness(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
