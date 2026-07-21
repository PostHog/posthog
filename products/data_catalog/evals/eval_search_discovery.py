"""Catalog-noise control for governed-metric discovery.

Catalog-first steering must not overcorrect: a seeded catalog whose metric names share
keywords with an ordinary tool task must not derail that task. The agent should create
the flag with the feature-flag tool and never detour through the metrics catalog.

To run::

    flox activate -- bash -c "hogli evals eval_search_discovery"
"""

from __future__ import annotations

from products.data_catalog.evals.constants import CONTROL_FLAG_KEY
from products.data_catalog.evals.scorers import MetricsCatalogNotQueried
from products.data_catalog.evals.seeders import seed_metric_listing_catalog
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_search_discovery(ctx: EvalContext) -> None:
    """Do governed metrics in search results leave ordinary tool tasks undisturbed?"""
    cases = [
        # The seeded catalog holds revenue metrics whose names share tokens with this
        # prompt — the flag must still get created, with no SQL detour through the
        # metrics catalog.
        SandboxedEvalCase(
            name="tool_task_undistracted_by_metrics",
            prompt=f"Create a feature flag called {CONTROL_FLAG_KEY} rolled out to 25% of users.",
            expected={"metrics_catalog_not_queried": {}},
            setup=seed_metric_listing_catalog,
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-catalog-search-control-cli",
        cases=cases,
        scorers=[RequiredToolCall(["create-feature-flag"]), MetricsCatalogNotQueried()],
        ctx=ctx,
    )
