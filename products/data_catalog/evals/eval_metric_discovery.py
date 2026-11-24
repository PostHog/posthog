"""Metric discovery evals: find the governed metric a question means in a catalog full of other metrics.

Run it once per surface:

    ./bin/hogli evals eval_metric_discovery --surface app --skill-delivery bundled --provider modal
    ./bin/hogli evals eval_metric_discovery --surface mcp --skill-delivery exec --provider modal
"""

from __future__ import annotations

from products.data_catalog.evals.catalog_seeders import (
    seed_catalog_with_account_engagement,
    seed_catalog_with_files_page_actions,
    seed_catalog_with_mrr,
    seed_catalog_with_pageviews_by_page,
    seed_catalog_with_power_downloaders,
    seed_catalog_with_proposed_download_adoption,
)
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    FILES_PAGE_ACTIONS_METRIC,
    MRR_METRIC,
    NEW_USER_DOWNLOAD_ADOPTION_METRIC,
    PAGEVIEWS_BY_PAGE_METRIC,
    POWER_DOWNLOADERS_METRIC,
)
from products.data_catalog.evals.offline_config import offline_suite
from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    MetricFound,
    MetricsCatalogBeforeDataDiscovery,
    SemanticLayerAnswer,
    TrustBadgeShown,
)
from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext

# No prompt names the metric or asks for a saved metric, so the agent must think to look in the catalog
# and then match the request to the metric's description.
_ACCOUNT_ACTIVITY_PROMPTS = (
    ("report", "Prepare a report on account activity for the last month."),
    ("health_check", "How engaged are our customer accounts lately? I want the week-by-week picture."),
    ("cs_review", "For the customer success review, how many companies used the product each week recently?"),
)


async def eval_metric_discovery(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="search_exact_name",
            prompt="Run our monthly recurring revenue metric.",
            expected={
                "metric_found": {"metric_name": MRR_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"metric_name": MRR_METRIC.name, "outcome": "succeeded"},
                "trust_badge": {"shown": True},
            },
            setup=seed_catalog_with_mrr,
        ),
        SandboxedEvalCase(
            name="search_synonym_in_noise",
            prompt="What's our ARR?",
            expected={
                "metric_found": {"metric_name": MRR_METRIC.name},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find the approved {MRR_METRIC.name} metric although the user asked for ARR, run it, and "
                        "derive ARR as 12 times MRR. Say that ARR is derived from the governed MRR metric and that "
                        "no governed ARR metric exists. Do not re-derive revenue from raw events."
                    )
                },
            },
            setup=seed_catalog_with_mrr,
        ),
        *(
            SandboxedEvalCase(
                name=f"search_by_description_{variant}",
                prompt=prompt,
                expected={
                    "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                    "canonical_metric_run": {
                        "metric_name": ACCOUNT_ENGAGEMENT_METRIC.name,
                        "outcome": "succeeded",
                        "allow_other_metrics": True,
                    },
                    "semantic_layer_answer": {
                        "expected_behavior": (
                            f"Find and run the approved {ACCOUNT_ENGAGEMENT_METRIC.name} metric, and report its "
                            "weekly counts of active accounts as the governed account activity numbers. Other "
                            "catalog metrics may add context, but the answer must not replace the governed weekly "
                            "account counts with a figure derived from raw events."
                        )
                    },
                },
                setup=seed_catalog_with_account_engagement,
            )
            for variant, prompt in _ACCOUNT_ACTIVITY_PROMPTS
        ),
        SandboxedEvalCase(
            name="search_proposed_metric_for_adoption",
            prompt="Are new users picking up file downloads? Show me adoption week by week.",
            expected={
                "metric_found": {"metric_name": NEW_USER_DOWNLOAD_ADOPTION_METRIC.name},
                "canonical_metric_run": {"metric_name": NEW_USER_DOWNLOAD_ADOPTION_METRIC.name, "outcome": "succeeded"},
                "trust_badge": {"shown": False},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find the {NEW_USER_DOWNLOAD_ADOPTION_METRIC.name} metric, run it, and report the weekly "
                        "share of new signups who downloaded a file within 7 days. Say that the metric is proposed, "
                        "not approved, so its numbers are not the governed definition. Say that the newest week is "
                        "low because its signups have had less than 7 days. Do not use the share of all active users "
                        "who downloaded, because that measures a different group."
                    )
                },
            },
            setup=seed_catalog_with_proposed_download_adoption,
        ),
        # These three name an entity or a screen, not a measure, which is the shape where agents skip the catalog.
        SandboxedEvalCase(
            name="search_metric_for_quiet_accounts",
            prompt="Which accounts have gone quiet over the last two weeks, and how was their activity trending before that?",
            expected={
                "metric_found": {"metric_name": ACCOUNT_ENGAGEMENT_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {ACCOUNT_ENGAGEMENT_METRIC.name} in the catalog before exploring the schema, and base "
                        "the weekly activity trend on its definition of an active account. Name the accounts with no "
                        "activity in the last two weeks, and label any per-account breakdown as an adaptation of the "
                        "governed metric."
                    )
                },
            },
            setup=seed_catalog_with_account_engagement,
        ),
        SandboxedEvalCase(
            name="search_metric_for_page_clicks",
            prompt="What do people click most on the files page? Are they mostly opening files, uploading, or deleting?",
            expected={
                "metric_found": {"metric_name": FILES_PAGE_ACTIONS_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"metric_name": FILES_PAGE_ACTIONS_METRIC.name, "outcome": "succeeded"},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {FILES_PAGE_ACTIONS_METRIC.name} in the catalog before exploring the schema, run it, "
                        "and report that downloads are by far the most common action on the files page, with the "
                        "number of people behind each action."
                    )
                },
            },
            setup=seed_catalog_with_files_page_actions,
        ),
        SandboxedEvalCase(
            name="search_metric_for_power_users",
            prompt=(
                "Our key metrics dashboard already gives paid accounts more weight. I want heavy downloaders to count "
                "for more too. How should we define them?"
            ),
            expected={
                "metric_found": {"metric_name": POWER_DOWNLOADERS_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {POWER_DOWNLOADERS_METRIC.name} in the catalog and use its definition of a power user, "
                        "20 or more downloads in the trailing 30 days, instead of inventing a new threshold."
                    )
                },
            },
            setup=seed_catalog_with_power_downloaders,
        ),
        SandboxedEvalCase(
            name="search_metric_for_top_page",
            prompt="What's the most visited page this week?",
            expected={
                "metric_found": {"metric_name": PAGEVIEWS_BY_PAGE_METRIC.name},
                "metrics_catalog_before_data_discovery": {},
                "canonical_metric_run": {"metric_name": PAGEVIEWS_BY_PAGE_METRIC.name, "outcome": "succeeded"},
                "semantic_layer_answer": {
                    "expected_behavior": (
                        f"Find {PAGEVIEWS_BY_PAGE_METRIC.name} in the catalog before exploring the schema, run it, "
                        "and report that the home page (/) is the most visited page over the last 7 days, followed "
                        "by /files/, with the pageview count for each. Do not use a total page view metric, because "
                        "it does not rank pages."
                    )
                },
            },
            setup=seed_catalog_with_pageviews_by_page,
        ),
    ]

    await SandboxedEval(
        experiment_name="sandboxed-metric-discovery-cli",
        cases=cases,
        scorers=[
            MetricFound(),
            MetricsCatalogBeforeDataDiscovery(),
            CanonicalMetricRun(),
            TrustBadgeShown(),
            SemanticLayerAnswer(),
        ],
        ctx=ctx,
        offline_suite=offline_suite(
            "data_catalog/eval_metric_discovery::eval_metric_discovery",
            metrics=[
                "metric_found",
                "metrics_catalog_before_data_discovery",
                "canonical_metric_run",
                "trust_badge",
                "semantic_layer_answer",
            ],
        ),
    )
