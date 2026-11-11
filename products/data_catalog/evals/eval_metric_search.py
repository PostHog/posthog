"""Does catalog search find the metric a query means, and say so when the catalog has none?

``metric-search-lexical`` runs weighted full-text search, exact and acronym matches, and the typo
fallback over labeled cases. It is the baseline that any other search variant must beat.

The suite seeds the invented catalog in ``metric_search_cases.py`` into a fresh team and runs every
case through ``search_metrics``. Scores are deterministic. ``metric_search_recall_<type>`` gives
recall per case type: the share of cases whose expected metric is among the hits the search returns,
10 by default. ``metric_search_correct_no_match`` scores the real-gap cases, and
``metric_search_sibling_ranked_above`` scores the near-sibling cases.

Word matching cannot find a related-word case, so lexical search scores 0 on that row by design.

No CI job runs this suite. Run it by hand:
    hogli evals eval_metric_search
"""

from __future__ import annotations

import uuid
import asyncio
from typing import Any

from posthog.models import Organization, Team

from products.data_catalog.evals.metric_search_cases import SEARCH_CASES, SearchCase
from products.data_catalog.evals.metric_search_runner import (
    LEXICAL,
    SearchVariant,
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


def _create_team(variant: SearchVariant) -> int:
    organization = Organization.objects.create(name=f"Metric search eval ({variant.name}-{uuid.uuid4().hex[:8]})")
    team = Team.objects.create(organization=organization, name="Metric search eval")
    seed_metric_search_catalog(team.id)
    return team.id


async def _run_variant(ctx: EvalContext, variant: SearchVariant, suite_key: str) -> None:
    seeded: dict[str, int] = {}
    seed_lock = asyncio.Lock()

    async def team_id() -> int:
        async with seed_lock:
            if "team_id" not in seeded:
                seeded["team_id"] = await asyncio.to_thread(_create_team, variant)
        return seeded["team_id"]

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        search_case: SearchCase = _CASES_BY_NAME[case.name]
        # A seeding or query error propagates, so the harness counts it as an infra error, not a 0 score.
        output = await asyncio.to_thread(run_case, await team_id(), search_case, variant)
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
