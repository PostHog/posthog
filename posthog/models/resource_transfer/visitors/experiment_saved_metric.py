from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models import Action, Cohort
from posthog.models.resource_transfer.types import ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import build_edges_for_ids
from posthog.models.resource_transfer.visitors.insight import InsightVisitor


class ExperimentSavedMetricVisitor(
    ResourceTransferVisitor,
    kind="ExperimentSavedMetric",
    excluded_fields=["created_at", "updated_at"],
    friendly_name="Saved experiment metric",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.experiments.backend.models.experiment import ExperimentSavedMetric

        return ExperimentSavedMetric

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        query = resource.query
        if not isinstance(query, dict):
            return []

        cohort_ids = InsightVisitor._extract_cohort_ids(None, query)
        action_ids = InsightVisitor._extract_action_ids(None, query)

        edges: list[ResourceTransferEdge] = []
        edges.extend(build_edges_for_ids(cohort_ids, Cohort, "cohort", _rewrite_cohort_in_saved_metric_payload))
        edges.extend(build_edges_for_ids(action_ids, Action, "action", _rewrite_action_in_saved_metric_payload))
        return edges


def _rewrite_cohort_in_saved_metric_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    if isinstance(result.get("query"), dict):
        result["query"] = InsightVisitor._rewrite_cohort_id_in_query(result["query"], int(old_pk), int(new_pk))
    return result


def _rewrite_action_in_saved_metric_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    if isinstance(result.get("query"), dict):
        result["query"] = InsightVisitor._rewrite_action_id_in_query(result["query"], int(old_pk), int(new_pk))
    return result
