"""Does catalog search find the metric a query means, and say so when the catalog has none?

The plan's ship gate for semantic search compares two variants on the same labeled cases:

- ``metric-search-lexical``: weighted full-text search, exact and acronym matches, typo fallback.
- ``metric-search-hybrid``: the same, merged with cosine similarity over embeddings.

Each suite seeds the invented catalog in ``metric_search_cases.py`` into a fresh team and runs every
case through ``search_metrics``. Scores are deterministic. ``metric_search_recall_<type>`` gives
recall per case type: the share of cases whose expected metric is among the hits the search returns,
10 by default. ``metric_search_correct_no_match`` scores the real-gap cases, and
``metric_search_sibling_ranked_above`` scores the near-sibling cases.

Semantic search ships only if the hybrid suite raises the related-word and paraphrased-question rows
over the lexical suite, without lowering the exact-name and near-sibling rows.

No CI job runs these suites. Run them by hand. The hybrid suite also needs OPENAI_API_KEY, because it
embeds the catalog and the queries with the worker's model through OpenAI directly:
    hogli evals eval_metric_search
    hogli evals eval_metric_search_hybrid --eval related_
"""

from __future__ import annotations

import uuid
import asyncio
from typing import Any

from posthog.models import Organization, Team

from products.data_catalog.evals.metric_search_cases import SEARCH_CASES, SearchCase
from products.data_catalog.evals.metric_search_runner import (
    HYBRID,
    LEXICAL,
    Embedder,
    SearchVariant,
    openai_embedder,
    run_case,
    score_case,
    seed_metric_search_catalog,
)
from products.data_catalog.evals.metric_search_scorers import metric_search_scorers
from products.data_catalog.evals.offline_config import offline_suite
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval

SUITE_KIND = SuiteKind.ONE_SHOT

_CASES_BY_NAME = {case.name: case for case in SEARCH_CASES}


def _eval_cases() -> list[BaseEvalCase]:
    return [
        BaseEvalCase(name=case.name, prompt=" | ".join(case.queries), metadata={"case_type": case.case_type.value})
        for case in SEARCH_CASES
    ]


def _create_team(variant: SearchVariant, embed: Embedder | None) -> int:
    organization = Organization.objects.create(name=f"Metric search eval ({variant.name}-{uuid.uuid4().hex[:8]})")
    team = Team.objects.create(organization=organization, name="Metric search eval")
    seed_metric_search_catalog(team.id, embed=embed)
    return team.id


async def _run_variant(ctx: EvalContext, variant: SearchVariant, suite_key: str) -> None:
    embed = openai_embedder() if variant.semantic else None
    seeded: dict[str, int] = {}
    seed_lock = asyncio.Lock()

    async def team_id() -> int:
        async with seed_lock:
            if "team_id" not in seeded:
                seeded["team_id"] = await asyncio.to_thread(_create_team, variant, embed)
        return seeded["team_id"]

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        search_case: SearchCase = _CASES_BY_NAME[case.name]
        # A seeding or query error propagates, so the harness counts it as an infra error, not a 0 score.
        output = await asyncio.to_thread(run_case, await team_id(), search_case, variant, embed=embed)
        output["scores"] = score_case(search_case, output["ranked"], output["confident_match"])
        output["last_message"] = ", ".join(output["ranked"]) or "no hits"
        return output

    scorers = metric_search_scorers()
    await OneShotEval(
        experiment_name=f"metric-search-{variant.name}",
        offline_suite=offline_suite(suite_key, metrics=[scorer._name() for scorer in scorers], suite_kind=SUITE_KIND),
        cases=_eval_cases(),
        scorers=scorers,
        task=task,
        ctx=ctx,
    )


async def eval_metric_search_lexical(ctx: EvalContext) -> None:
    await _run_variant(ctx, LEXICAL, "data_catalog/eval_metric_search::eval_metric_search_lexical")


async def eval_metric_search_hybrid(ctx: EvalContext) -> None:
    await _run_variant(ctx, HYBRID, "data_catalog/eval_metric_search::eval_metric_search_hybrid")
