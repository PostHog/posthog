"""Table choice evals: pick the right warehouse table from its trust signals, and reject one after looking at it.

Every case seeds queryable tables, so it needs object storage. Run it once per surface:

    EVAL_SURFACE=app ./bin/hogli evals eval_table_choice --skill-delivery bundled --provider modal
    EVAL_SURFACE=mcp ./bin/hogli evals eval_table_choice --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import (
    seed_amount_currency_tables,
    seed_deal_account_relationship,
    seed_deal_tables,
)
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNTS_DECOY_TABLE,
    ACCOUNTS_TABLE,
    DEALS_CLOSED_WON_TOTAL,
    DEALS_LEGACY_CLOSED_WON_TOTAL,
    DEALS_LEGACY_TABLE,
    DEALS_TABLE,
    DEALS_V3_TABLE,
    LOCAL_AMOUNT_TABLE,
    USD_AMOUNT_TABLE,
    USD_AMOUNT_TOTAL,
    closed_won_by_industry,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scorers import (
    AnswerTableQueried,
    AnswerValueStated,
    SemanticLayerAnswer,
    SemanticMetadataQueried,
    TableInspected,
)
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import SourcesAvoided, SourcesConsulted


def _names(table: str) -> list[str]:
    """A synced table answers to its stored name and to the dotted name HogQL builds from the source."""
    return [table, f"postgres.{table}"]


def _usd(value: float) -> str:
    return f"{value:.2f}"


def _industry_totals() -> str:
    return ", ".join(f"{industry} {total:,.0f} USD" for industry, total in sorted(closed_won_by_industry().items()))


async def eval_table_choice(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="pick_certified_over_deprecated",
            prompt="What's the total value of our closed-won deals?",
            expected={
                "semantic_metadata_queried": {
                    "surface": "information_schema.tables",
                    "required_columns": ["certification"],
                },
                "sources_consulted": {"tables": [_names(DEALS_TABLE)]},
                "sources_avoided": {
                    "tables": [*_names(DEALS_LEGACY_TABLE), *_names(DEALS_V3_TABLE)],
                    "scope": "answer",
                },
                "answer_value_stated": {"value": _usd(DEALS_CLOSED_WON_TOTAL)},
            },
            setup=seed_deal_tables,
        ),
        SandboxedEvalCase(
            name="reject_empty_after_inspection",
            prompt=f"Use {DEALS_V3_TABLE} to total our closed-won deal value.",
            expected={
                "table_inspected": {"table": _names(DEALS_V3_TABLE)},
                "sources_avoided": {"tables": _names(DEALS_V3_TABLE), "scope": "answer"},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Look at {DEALS_V3_TABLE} and find that it has no rows. Say so instead of reporting a "
                        f"total of 0, and point to the certified {DEALS_TABLE}, whose closed-won total is "
                        f"{DEALS_CLOSED_WON_TOTAL:,.0f} USD. Using the deprecated {DEALS_LEGACY_TABLE} "
                        f"({DEALS_LEGACY_CLOSED_WON_TOTAL:,.0f} USD) is a failure."
                    )
                },
            },
            setup=seed_deal_tables,
        ),
        SandboxedEvalCase(
            name="column_descriptions_drive_choice",
            prompt="Which of our deal tables stores amounts in US dollars? Give me the total USD amount across its deals.",
            expected={
                "semantic_metadata_queried": {
                    "surface": "information_schema.columns",
                    "required_columns": ["description"],
                },
                "answer_table_queried": {"tables": _names(USD_AMOUNT_TABLE), "decoys": _names(LOCAL_AMOUNT_TABLE)},
                "answer_value_stated": {"value": _usd(USD_AMOUNT_TOTAL)},
            },
            setup=seed_amount_currency_tables,
        ),
        SandboxedEvalCase(
            name="connected_table_via_relationship",
            prompt="What's our closed-won deal value by account industry?",
            expected={
                "semantic_metadata_queried": {
                    "surface": "information_schema.relationships",
                    "required_columns": ["confidence", "reasoning"],
                },
                # The decoy join labels every account "unknown", so the media total only comes from the reviewed join.
                # A lazy join (`deals.account.industry`) never names the joined table, so the value is the check.
                "answer_value_stated": {"value": _usd(closed_won_by_industry()["media"])},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find the reviewed relationship from {DEALS_TABLE} to {ACCOUNTS_TABLE} and join through "
                        f"it, not through the unreviewed join to {ACCOUNTS_DECOY_TABLE}. Report closed-won value "
                        f"by industry: {_industry_totals()}."
                    )
                },
            },
            setup=seed_deal_account_relationship,
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-table-choice-cli",
        cases=cases,
        scorers=[
            SemanticMetadataQueried(),
            SourcesConsulted(),
            SourcesAvoided(),
            TableInspected(),
            AnswerTableQueried(),
            AnswerValueStated(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_table_choice::eval_table_choice",
            metrics=[
                "semantic_metadata_queried",
                "sources_consulted",
                "sources_avoided",
                "table_inspected",
                "answer_table_queried",
                "answer_value_stated",
                "semantic_layer_answer",
            ],
        ),
    )
