"""
Shared helpers for extracting and rewriting JSON-embedded foreign-key
references (cohort IDs, action IDs) that appear inside untyped JSON
columns such as ``Insight.filters``, ``Insight.query``,
``Cohort.filters``, and ``Cohort.groups``.

Both ``InsightVisitor`` and ``CohortVisitor`` delegate to these
functions so the recursive property-group walking logic lives in one
place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import models

from posthog.models.resource_transfer.types import ResourceMap, ResourcePayload, ResourceTransferEdge, RewriteRelationFn

RewritePayloadFn = Callable[[ResourcePayload, Any, Any], ResourcePayload]


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def collect_cohort_ids_from_properties(properties: Any) -> set[int]:
    """Walk a (possibly nested) property-group structure and return every
    referenced cohort ID.

    Handles both flat lists::

        [{"type": "cohort", "value": 42}, ...]

    and grouped formats::

        {"type": "AND", "values": [{"type": "OR", "values": [...]}]}
    """
    ids: set[int] = set()
    if isinstance(properties, list):
        for prop in properties:
            if isinstance(prop, dict) and prop.get("type") == "cohort" and prop.get("value") is not None:
                ids.add(int(prop["value"]))
    elif isinstance(properties, dict):
        if properties.get("type") == "cohort" and properties.get("value") is not None:
            ids.add(int(properties["value"]))
        for group in properties.get("values", []):
            if isinstance(group, dict):
                ids.update(collect_cohort_ids_from_properties(group.get("values", [])))
    return ids


# ---------------------------------------------------------------------------
# Rewriters
# ---------------------------------------------------------------------------


def rewrite_cohort_id_in_properties(properties: Any, old_pk: int, new_pk: int) -> Any:
    """Return a shallow-copy of *properties* with *old_pk* replaced by *new_pk*
    wherever a cohort reference appears."""
    if isinstance(properties, list):
        result = []
        for prop in properties:
            if (
                isinstance(prop, dict)
                and prop.get("type") == "cohort"
                and prop.get("value") is not None
                and int(prop["value"]) == old_pk
            ):
                result.append({**prop, "value": new_pk})
            else:
                result.append(prop)
        return result
    elif isinstance(properties, dict):
        result_dict = {**properties}
        if (
            result_dict.get("type") == "cohort"
            and result_dict.get("value") is not None
            and int(result_dict["value"]) == old_pk
        ):
            result_dict["value"] = new_pk
        if "values" in result_dict:
            new_values = []
            for group in result_dict["values"]:
                if isinstance(group, dict):
                    new_group = {**group}
                    if "values" in new_group:
                        new_group["values"] = rewrite_cohort_id_in_properties(new_group["values"], old_pk, new_pk)
                    new_values.append(new_group)
                else:
                    new_values.append(group)
            result_dict["values"] = new_values
        return result_dict
    return properties


def rewrite_cohort_breakdown(breakdown: Any, old_pk: int, new_pk: int) -> Any:
    """Rewrite a cohort breakdown value (scalar or list)."""
    if isinstance(breakdown, list):
        return [new_pk if isinstance(item, int) and item == old_pk else item for item in breakdown]
    elif isinstance(breakdown, int) and breakdown == old_pk:
        return new_pk
    return breakdown


# ---------------------------------------------------------------------------
# Edge builder factory
# ---------------------------------------------------------------------------


def make_json_id_rewriter(
    target_model: type[models.Model],
    old_pk: Any,
    rewrite_fn: RewritePayloadFn,
) -> RewriteRelationFn:
    """Build a ``RewriteRelationFn`` that resolves the new PK from the
    resource map and then delegates to *rewrite_fn* to patch the payload.

    Parameters
    ----------
    target_model:
        The Django model class being referenced (e.g. ``Action``, ``Cohort``).
    old_pk:
        The original primary key embedded in JSON.
    rewrite_fn:
        ``(payload, old_pk, new_pk) -> payload`` -- the caller-supplied
        function that knows *where* inside the payload to substitute.
    """

    def _rewrite(
        payload: ResourcePayload,
        resource_map: ResourceMap,
    ) -> ResourcePayload:
        from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

        target_visitor = ResourceTransferVisitor.get_visitor(target_model)
        if target_visitor is None:
            raise TypeError(f"Could not rewrite {target_model.__name__} because it has no configured visitor")

        vertex = resource_map.get((target_visitor.kind, old_pk))
        if vertex is None:
            raise ValueError(
                f"Could not rewrite JSON reference to {target_model.__name__}(pk={old_pk}): resource not found in map"
            )

        if vertex.duplicated_resource is None:
            raise ValueError(
                f"Could not rewrite JSON reference to {target_model.__name__}(pk={old_pk}): resource not duplicated yet"
            )

        new_pk = vertex.duplicated_resource.pk
        return rewrite_fn(payload, old_pk, new_pk)

    return _rewrite


def build_edges_for_ids(
    ids: set[int],
    target_model: type[models.Model],
    label_prefix: str,
    rewrite_fn: RewritePayloadFn,
) -> list[ResourceTransferEdge]:
    """Turn a set of extracted IDs into ``ResourceTransferEdge`` objects
    with the shared rewriter."""
    return [
        ResourceTransferEdge(
            name=f"{label_prefix}:{pk}",
            target_model=target_model,
            target_primary_key=pk,
            rewrite_relation=make_json_id_rewriter(target_model, pk, rewrite_fn),
        )
        for pk in ids
    ]
