"""Cohort, action, and holdout references inside :class:`posthog.models.feature_flag.FeatureFlag` ``filters`` JSON."""

from __future__ import annotations

from typing import Any

from posthog.models.resource_transfer.types import ResourcePayload
from posthog.models.resource_transfer.visitors.cohort import CohortVisitor
from posthog.models.resource_transfer.visitors.common import rewrite_cohort_id_in_properties


def collect_cohort_ids_from_flag_filters(filters: dict | None) -> set[int]:
    if not filters:
        return set()
    ids: set[int] = set()
    for key in ("groups", "super_groups"):
        for group in filters.get(key) or []:
            if isinstance(group, dict):
                ids.update(CohortVisitor._extract_cohort_ids({"properties": group.get("properties")}))
    return ids


def collect_action_ids_from_flag_filters(filters: dict | None) -> set[int]:
    if not filters:
        return set()
    ids: set[int] = set()
    for key in ("groups", "super_groups"):
        for group in filters.get(key) or []:
            if isinstance(group, dict):
                ids.update(
                    CohortVisitor._extract_action_ids({"properties": group.get("properties")}),
                )
    return ids


def get_holdout_id_from_flag_filters(filters: dict | None) -> int | None:
    if not filters:
        return None
    holdout = filters.get("holdout")
    if isinstance(holdout, dict) and holdout.get("id") is not None:
        return int(holdout["id"])
    return None


def rewrite_cohort_in_flag_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    if result.get("filters"):
        result["filters"] = _rewrite_cohort_in_filters_dict(result["filters"], int(old_pk), int(new_pk))
    return result


def rewrite_action_in_flag_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    if result.get("filters"):
        result["filters"] = _rewrite_action_in_filters_dict(result["filters"], int(old_pk), int(new_pk))
    return result


def rewrite_holdout_in_flag_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    filters = result.get("filters")
    if isinstance(filters, dict):
        holdout = filters.get("holdout")
        if isinstance(holdout, dict) and holdout.get("id") is not None and int(holdout["id"]) == int(old_pk):
            result["filters"] = {**filters, "holdout": {**holdout, "id": int(new_pk)}}
    return result


def _rewrite_cohort_in_filters_dict(filters: dict, old_pk: int, new_pk: int) -> dict:
    result = {**filters}
    for key in ("groups", "super_groups"):
        if key not in result or not isinstance(result[key], list):
            continue
        new_groups = []
        for group in result[key]:
            if isinstance(group, dict) and group.get("properties") is not None:
                new_groups.append(
                    {
                        **group,
                        "properties": rewrite_cohort_id_in_properties(group["properties"], old_pk, new_pk),
                    }
                )
            else:
                new_groups.append(group)
        result[key] = new_groups
    return result


def _rewrite_action_in_filters_dict(filters: dict, old_pk: int, new_pk: int) -> dict:
    result = {**filters}
    for key in ("groups", "super_groups"):
        if key not in result or not isinstance(result[key], list):
            continue
        new_groups = []
        for group in result[key]:
            if isinstance(group, dict) and group.get("properties") is not None:
                new_groups.append(
                    {
                        **group,
                        "properties": CohortVisitor._rewrite_action_id_in_properties(
                            group["properties"], old_pk, new_pk
                        ),
                    }
                )
            else:
                new_groups.append(group)
        result[key] = new_groups
    return result
