"""Fold the model breakdown on AI observability dashboards that already exist.

The dashboard is created once per team from the template, so a template change only
reaches teams that have not opened AI observability yet. This backfill carries the same
change to the tiles that already exist, and only to the ones whose query still matches
what the template wrote, so an edited tile keeps the query its owner chose.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.ai_observability.backend.model_breakdown import (
    MODEL_BREAKDOWN_DESCRIPTION,
    RAW_MODEL_BREAKDOWN_FILTER,
    normalized_model_breakdown_filter,
)
from products.product_analytics.backend.models.insight import Insight

# Names the template gives the two tiles that break down on the model.
MODEL_TILE_NAMES = ("Cost by model (USD)", "Generation latency by model (median)")

AI_OBSERVABILITY_DASHBOARD_TAG = "llm-analytics"


@frozen
class BackfillReport:
    candidates: int
    folded: tuple[int, ...]
    skipped: tuple[int, ...]


def model_breakdown_tiles(team_ids: Sequence[int] | None = None) -> Iterable[Insight]:
    queryset = Insight.objects.filter(
        name__in=MODEL_TILE_NAMES,
        dashboard_tiles__dashboard__deleted=False,
        dashboard_tiles__dashboard__creation_mode="unlisted",
        dashboard_tiles__dashboard__tagged_items__tag__name=AI_OBSERVABILITY_DASHBOARD_TAG,
    )
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)
    return queryset.distinct().order_by("id")


def fold_model_breakdown(team_ids: Sequence[int] | None = None, apply: bool = False) -> BackfillReport:
    candidates = 0
    folded: list[int] = []
    skipped: list[int] = []

    for insight in model_breakdown_tiles(team_ids):
        candidates += 1
        folded_query = fold_query(insight.query)

        if folded_query is None:
            skipped.append(insight.id)
            continue

        folded.append(insight.id)

        if not apply:
            continue

        insight.query = folded_query
        insight.description = MODEL_BREAKDOWN_DESCRIPTION
        insight.save(update_fields=["query", "description", "updated_at"])

    return BackfillReport(candidates=candidates, folded=tuple(folded), skipped=tuple(skipped))


def fold_query(query: Any) -> dict[str, Any] | None:
    """Return the query with a folded model breakdown, or None if the template no longer owns it.

    The result is a new dict rather than an edit of the loaded one, because `Insight.save`
    compares `query` against the value it read at load time to decide whether to regenerate
    `query_metadata`, and an in-place edit changes both sides of that comparison.
    """
    if not isinstance(query, dict):
        return None

    source = query.get("source")

    if not isinstance(source, dict) or source.get("kind") != "TrendsQuery":
        return None

    if source.get("breakdownFilter") != RAW_MODEL_BREAKDOWN_FILTER:
        return None

    return {**query, "source": {**source, "breakdownFilter": normalized_model_breakdown_filter()}}
