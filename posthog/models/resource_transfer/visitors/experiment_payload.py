"""
Helpers for extracting and rewriting cohort/action references embedded in
:class:`~products.experiments.backend.models.experiment.Experiment` JSON fields.
"""

from __future__ import annotations

from typing import Any

from posthog.models.resource_transfer.types import ResourcePayload
from posthog.models.resource_transfer.visitors.insight import InsightVisitor


def collect_cohort_and_action_ids_from_experiment_json(resource: Any) -> tuple[set[int], set[int]]:
    cohort_ids: set[int] = set()
    action_ids: set[int] = set()

    for blob in (
        resource.filters,
        resource.parameters,
        resource.metrics,
        resource.metrics_secondary,
        resource.exposure_criteria,
        resource.stats_config,
        resource.scheduling_config,
        resource.variants,
    ):
        c, a = _collect_ids_from_json_blob(blob)
        cohort_ids.update(c)
        action_ids.update(a)

    return cohort_ids, action_ids


def _collect_ids_from_json_blob(blob: Any) -> tuple[set[int], set[int]]:
    cohort_ids: set[int] = set()
    action_ids: set[int] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "query" in o and isinstance(o["query"], dict):
                cohort_ids.update(InsightVisitor._extract_cohort_ids(None, o["query"]))
                action_ids.update(InsightVisitor._extract_action_ids(None, o["query"]))
            if "filters" in o and isinstance(o["filters"], dict):
                cohort_ids.update(InsightVisitor._extract_cohort_ids(o["filters"], None))
                action_ids.update(InsightVisitor._extract_action_ids(o["filters"], None))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(blob)
    return cohort_ids, action_ids


def rewrite_cohort_in_experiment_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    for field in (
        "filters",
        "parameters",
        "metrics",
        "metrics_secondary",
        "exposure_criteria",
        "stats_config",
        "scheduling_config",
        "variants",
    ):
        if field in result and result[field] is not None:
            result[field] = _rewrite_cohort_ids_in_json(result[field], int(old_pk), int(new_pk))
    return result


def rewrite_action_in_experiment_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    for field in (
        "filters",
        "parameters",
        "metrics",
        "metrics_secondary",
        "exposure_criteria",
        "stats_config",
        "scheduling_config",
        "variants",
    ):
        if field in result and result[field] is not None:
            result[field] = _rewrite_action_ids_in_json(result[field], int(old_pk), int(new_pk))
    return result


def _rewrite_cohort_ids_in_json(obj: Any, old_pk: int, new_pk: int) -> Any:
    if isinstance(obj, dict):
        if "query" in obj and isinstance(obj["query"], dict):
            obj = {
                **obj,
                "query": InsightVisitor._rewrite_cohort_id_in_query(obj["query"], old_pk, new_pk),
            }
        if "filters" in obj and isinstance(obj["filters"], dict):
            obj = {
                **obj,
                "filters": InsightVisitor._rewrite_cohort_id_in_filters(obj["filters"], old_pk, new_pk),
            }
        return {k: _rewrite_cohort_ids_in_json(v, old_pk, new_pk) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_cohort_ids_in_json(item, old_pk, new_pk) for item in obj]
    return obj


def _rewrite_action_ids_in_json(obj: Any, old_pk: int, new_pk: int) -> Any:
    if isinstance(obj, dict):
        if "query" in obj and isinstance(obj["query"], dict):
            obj = {
                **obj,
                "query": InsightVisitor._rewrite_action_id_in_query(obj["query"], old_pk, new_pk),
            }
        if "filters" in obj and isinstance(obj["filters"], dict):
            obj = {
                **obj,
                "filters": InsightVisitor._rewrite_action_id_in_filters(obj["filters"], old_pk, new_pk),
            }
        return {k: _rewrite_action_ids_in_json(v, old_pk, new_pk) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_action_ids_in_json(item, old_pk, new_pk) for item in obj]
    return obj
