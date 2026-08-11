"""Metric-authoring evals for the sandboxed agent.

Each case asks the agent to save a metric to the governed catalog and grades the write itself:
the ``description`` must stay a 1-3 sentence statement of business meaning (checked both by a
deterministic length bar and a judge that rejects query narration). The markdown-definition case
is the strongest verbosity temptation: a multi-step calculation invites restating the steps in
the description instead of leaving them in the definition.

No seeder: creation runs against the plain per-case Hedgebox team.

To run a single case::

    flox activate -- bash -c "hogli evals eval_metric_authoring --eval metric_create_concise_description"
"""

from __future__ import annotations

from products.data_catalog.evals.constants import METRIC_CREATE_TOOL
from products.data_catalog.evals.scorers import MetricDescriptionConcise, MetricDescriptionQuality
from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_metric_authoring(ctx: EvalContext) -> None:
    """When the agent writes a metric, is the description concise business meaning, not query narration?"""
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="metric_create_concise_description",
            prompt=(
                "We've agreed on an official MRR definition: the sum of paid_bill amount_usd over the "
                "trailing 30 days, excluding bills on the 'personal/free' plan. Save it to the data "
                "catalog as a governed metric so everyone uses the same definition."
            ),
            expected={
                "metric_description_concise": {},
                "metric_description_quality": {},
            },
        ),
        SandboxedEvalCase(
            name="metric_create_markdown_definition",
            prompt=(
                "Catalog an activation rate metric: the share of newly signed-up users who uploaded a "
                "file and upgraded their plan within 30 days of signup. The calculation takes several "
                "steps, so capture it however fits best."
            ),
            expected={
                "metric_description_concise": {},
                "metric_description_quality": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-metric-authoring-cli",
        cases=cases,
        scorers=[
            RequiredToolCall([METRIC_CREATE_TOOL], name="metric_create_called"),
            MetricDescriptionConcise(),
            MetricDescriptionQuality(),
        ],
        ctx=ctx,
    )
