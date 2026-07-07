"""Data-warehouse ``information_schema`` navigation evals for the sandboxed agent.

Each eval seeds a per-case team with hundreds of synthetic warehouse tables,
data-modeling views, and join relationships (``seed_warehouse_schema``), then grades
whether the agent uses ``system.information_schema`` to navigate the catalog at scale.
The ``mcp-sql-schema-discovery`` flag is forced on in the harness, so discovery runs
through ``execute-sql`` against ``system.information_schema.*`` and the dedicated
``read-data-warehouse-schema`` tool is gated off.

The cases are split into one eval function per capability so each Braintrust
experiment reports a clean, homogeneous scorecard (a single shared scorer list mixed
unrelated cases, since every scorer self-skips on cases it doesn't apply to):

* ``eval_dw_discovery`` — discover the right table/model among the noise, using
  agentic search (filter by name/description/data_type) rather than dumping the
  catalog.
* ``eval_dw_value_retrieval`` — retrieve a lookup needle with a real SQL query,
  including duck typing (a column declared ``String`` whose content is numeric).
* ``eval_dw_relationships`` — follow joins surfaced in
  ``information_schema.relationships``, single-hop and multi-hop.
* ``eval_dw_table_relevancy`` — pick the live table over a near-identical
  frozen/superseded decoy, distinguishable only by its annotation.

Prompts read like real user questions and never mention ``information_schema``.

To run a single eval::

    pytest ee/hogai/eval/sandboxed/data_warehouse/eval_information_schema.py::eval_dw_discovery
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.data_warehouse.scorers import (
    AgenticSearchUsed,
    AnswerQueryRanWhenExpected,
    InformationSchemaBeforeAnswer,
    InformationSchemaQueried,
    JoinPathTraversed,
    NeedleTableIdentified,
    NeedleValueRetrieved,
    RelationshipDiscovery,
    StaleTableAvoided,
    WarehouseAnswerCorrectness,
)
from ee.hogai.eval.sandboxed.data_warehouse.seeder import seed_warehouse_schema
from ee.hogai.eval.sandboxed.data_warehouse.synthesizer import (
    CHAIN_NEEDLE_HOP3,
    DESC_NEEDLE_TABLE,
    REL_NEEDLE_SOURCE,
    REL_NEEDLE_TARGET,
    RELEVANCY_NEEDLE_CURRENT,
    RELEVANCY_NEEDLE_STALE,
    RETRIEVAL_NEEDLE_ANSWER,
    RETRIEVAL_NEEDLE_EVENT_ID,
    RETRIEVAL_NEEDLE_TABLE,
    TYPE_NEEDLE_TABLE,
    VIEW_NEEDLE_NAME,
)
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


async def eval_dw_discovery(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Find the right table/model among hundreds via agentic search over the catalog."""
    cases: list[SandboxedEvalCase] = [
        # Discover a specific data model (view) among hundreds of tables. Graded on
        # discovery success (the right model is named), mechanism-agnostic: a view is
        # legitimately discoverable via the `view-list` tool, so this doesn't force
        # information_schema. The information_schema path is enforced by the search /
        # relationship cases, where read-data-warehouse-schema is gated off.
        SandboxedEvalCase(
            name="dw_discover_model_view",
            prompt=(
                "Which data model (view) in our warehouse produces the daily MRR numbers the "
                "finance dashboard reads? Just give me its name."
            ),
            expected={"needle_table_identified": {"table": VIEW_NEEDLE_NAME}},
            setup=seed_warehouse_schema,
        ),
        # Search by description text — the needle is found by filtering the catalog's
        # `description` column with a text pattern, not by guessing the opaque name.
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
        # Search by column data_type (an equality filter, not a text pattern).
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
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-warehouse-discovery-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaQueried(),
            AgenticSearchUsed(),
            NeedleTableIdentified(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_dw_value_retrieval(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Retrieve a lookup needle with a real SQL query, including duck-typed columns."""
    cases: list[SandboxedEvalCase] = [
        # Value lookup against the queryable needle: discover via information_schema,
        # then run a real row query to read the value out of a text-stored JSON payload.
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
        # Duck typing: declared String, content is numeric. The agent must cast to
        # compare (a plain text max returns the wrong row).
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
        experiment_name=f"sandboxed-warehouse-retrieval-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaQueried(),
            InformationSchemaBeforeAnswer(),
            NeedleValueRetrieved(),
            AnswerQueryRanWhenExpected(name="answer_query_ran"),
            WarehouseAnswerCorrectness(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_dw_relationships(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Follow joins surfaced in information_schema.relationships, single- and multi-hop."""
    cases: list[SandboxedEvalCase] = [
        # Single-hop relationship traversal. Graded deterministically by
        # relationship_discovery (relationships queried + both tables named); no LLM
        # judge, since the answer comes from the discovery query rather than a row query.
        SandboxedEvalCase(
            name="dw_relationship_traversal",
            prompt=(
                f"Our orders table '{REL_NEEDLE_SOURCE}' is linked to another warehouse table "
                f"through a defined relationship. Which table is it, and on what key do they join?"
            ),
            expected={
                "information_schema_queried": {},
                "relationship_discovery": {},
            },
            setup=seed_warehouse_schema,
        ),
        # Multi-hop / multi-table: assemble a two-hop join path by querying relationships
        # iteratively (orders -> account xref -> account owners). Tests combining several
        # discovered tables, not a single needle.
        SandboxedEvalCase(
            name="dw_multi_hop_join_path",
            prompt=(
                f"Starting from our orders table '{REL_NEEDLE_SOURCE}', I need to reach account-owner "
                "information. Which tables do I join through, in order, and on what keys? Trace the full path."
            ),
            expected={
                "information_schema_queried": {},
                "join_path_traversed": {},
                "warehouse_answer_correctness": {
                    "expected_answer": (
                        f"The path is two hops: {REL_NEEDLE_SOURCE} joins {REL_NEEDLE_TARGET} on account_ref, "
                        f"and {REL_NEEDLE_TARGET} joins {CHAIN_NEEDLE_HOP3} on owner_id. So orders -> account "
                        "xref -> account owners."
                    ),
                },
            },
            setup=seed_warehouse_schema,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-warehouse-relationships-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaQueried(),
            RelationshipDiscovery(),
            JoinPathTraversed(),
            WarehouseAnswerCorrectness(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )


async def eval_dw_table_relevancy(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Pick the live table over a near-identical frozen/superseded decoy."""
    cases: list[SandboxedEvalCase] = [
        # Two near-identical accounts dimensions, one live and one frozen/superseded.
        # Only the annotation distinguishes them, so the agent must read metadata (not
        # shortcut on the name) and recommend the current table while flagging the stale
        # one — not pick the decoy.
        SandboxedEvalCase(
            name="dw_table_relevancy_stale",
            prompt=(
                "We have more than one accounts dimension table in the warehouse. Which one should I "
                "use for current customer reporting, and what's wrong with the other one?"
            ),
            expected={
                "information_schema_queried": {},
                "agentic_search_used": {},
                "needle_table_identified": {"table": RELEVANCY_NEEDLE_CURRENT},
                "stale_table_avoided": {},
                "warehouse_answer_correctness": {
                    "expected_answer": (
                        f"Use {RELEVANCY_NEEDLE_CURRENT} — it is the live, daily-refreshed canonical "
                        f"accounts dimension. {RELEVANCY_NEEDLE_STALE} is deprecated/superseded: a frozen "
                        "2023 snapshot that is no longer refreshed, so it must not be used for current reporting."
                    ),
                },
            },
            setup=seed_warehouse_schema,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-warehouse-relevancy-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            InformationSchemaQueried(),
            AgenticSearchUsed(),
            NeedleTableIdentified(),
            StaleTableAvoided(),
            WarehouseAnswerCorrectness(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
