"""Seeder hooks installing governed metrics into a per-case team.

One dedicated seeder per catalog arm (approved / proposed / drifted) — the seeder contract
takes no per-case parameters, so case-specific state means a dedicated function, not knobs.
Each returns the seeded metric's identity and the values scorers grade against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from posthog.models.team import Team
from posthog.models.user import User

from products.data_catalog.backend.facade.api import approve_metric, upsert_metric
from products.data_catalog.evals.constants import (
    APPROVED_METRIC_DEFINITION,
    APPROVED_METRIC_DESCRIPTION,
    APPROVED_METRIC_DISTINGUISHING_FILTER,
    APPROVED_METRIC_NAME,
    DRIFTED_INSIGHT_MUTATED_QUERY,
    DRIFTED_INSIGHT_ORIGINAL_QUERY,
    DRIFTED_METRIC_DESCRIPTION,
    DRIFTED_METRIC_NAME,
    PROPOSED_METRIC_DEFINITION,
    PROPOSED_METRIC_DESCRIPTION,
    PROPOSED_METRIC_NAME,
)
from products.product_analytics.backend.models.insight import Insight

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = ["seed_approved_metric", "seed_proposed_metric", "seed_drifted_metric"]


def _team_and_user(context: CustomPromptSandboxContext) -> tuple[Team, User]:
    return Team.objects.get(pk=context.team_id), User.objects.get(pk=context.user_id)


def seed_approved_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    metric = upsert_metric(
        team=team,
        user=user,
        name=APPROVED_METRIC_NAME,
        description=APPROVED_METRIC_DESCRIPTION,
        unit="usd",
        definition=APPROVED_METRIC_DEFINITION,
    )
    approve_metric(metric, user)
    return {
        "metric": {
            "name": APPROVED_METRIC_NAME,
            "status": "approved",
            "definition_query": APPROVED_METRIC_DEFINITION["query"],
            "distinguishing_filter": APPROVED_METRIC_DISTINGUISHING_FILTER,
        }
    }


def seed_proposed_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    upsert_metric(
        team=team,
        user=user,
        name=PROPOSED_METRIC_NAME,
        description=PROPOSED_METRIC_DESCRIPTION,
        definition=PROPOSED_METRIC_DEFINITION,
    )
    return {"metric": {"name": PROPOSED_METRIC_NAME, "status": "proposed"}}


def seed_drifted_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    insight = Insight.objects.create(team=team, created_by=user, query=DRIFTED_INSIGHT_ORIGINAL_QUERY)
    metric = upsert_metric(
        team=team,
        user=user,
        name=DRIFTED_METRIC_NAME,
        description=DRIFTED_METRIC_DESCRIPTION,
        source_insight_short_id=insight.short_id,
    )
    approve_metric(metric, user)
    # Mutating the source insight after approval is what makes the metric read as drifted.
    Insight.objects.filter(pk=insight.pk).update(query=DRIFTED_INSIGHT_MUTATED_QUERY)
    return {"metric": {"name": DRIFTED_METRIC_NAME, "status": "approved", "is_drifted": True}}
