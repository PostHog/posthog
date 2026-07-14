"""Insight snapshotting and drift detection.

A metric created from an insight snapshots the insight's query at create time. Drift is computed
lazily at read time: the current insight query, canonicalized the same way, is compared to the stored
snapshot hash. Canonicalization runs ``upgrade()`` first so a schema migration never reads as drift.
"""

import json
import hashlib
from collections.abc import Iterable
from copy import deepcopy
from typing import Optional
from uuid import UUID

from posthog.schema_migrations.upgrade import upgrade

from products.product_analytics.backend.models.insight import Insight

from ..models import Metric


def canonical_query_hash(query: dict) -> str:
    """Stable hash of a query, invariant to key order and schema version."""
    return hashlib.sha256(json.dumps(upgrade(deepcopy(query)), sort_keys=True).encode()).hexdigest()


def effective_insight_query(insight: Insight) -> Optional[dict]:
    """The insight's query, converting legacy ``filters``-only insights via query_from_filters."""
    return insight.query or insight.query_from_filters


def fetch_insight(team_id: int, short_id: str, *, include_deleted: bool = False) -> Optional[Insight]:
    manager = Insight.objects_including_soft_deleted if include_deleted else Insight.objects
    return manager.filter(team_id=team_id, short_id=short_id).first()


def compute_drift(metrics: Iterable[Metric]) -> dict[UUID, bool]:
    """Map each metric id to whether its definition has drifted from its source insight.

    A missing or deleted source insight counts as drifted: absence of evidence never passes as
    verified lockstep. One bulk query over the linked insights, shared by the API and the catalog.
    """
    metrics = list(metrics)
    result: dict[UUID, bool] = {metric.id: False for metric in metrics}
    linked = [metric for metric in metrics if metric.source_insight_short_id]
    if not linked:
        return result

    short_ids = {metric.source_insight_short_id for metric in linked}
    team_ids = {metric.team_id for metric in linked}
    insights = Insight.objects_including_soft_deleted.filter(team_id__in=team_ids, short_id__in=short_ids)
    by_key: dict[tuple[int, str | None], Insight] = {
        (insight.team_id, insight.short_id): insight for insight in insights
    }

    for metric in linked:
        insight = by_key.get((metric.team_id, metric.source_insight_short_id))
        if insight is None or insight.deleted:
            result[metric.id] = True
            continue
        current_query = effective_insight_query(insight)
        if not current_query:
            result[metric.id] = True
            continue
        result[metric.id] = canonical_query_hash(current_query) != metric.source_insight_query_hash

    return result
