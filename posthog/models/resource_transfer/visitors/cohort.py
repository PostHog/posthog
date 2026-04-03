from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.types import ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import (
    build_edges_for_ids,
    collect_cohort_ids_from_properties,
    rewrite_cohort_id_in_properties,
)


class CohortVisitor(
    ResourceTransferVisitor,
    kind="Cohort",
    excluded_fields=[
        "is_calculating",
        "last_calculation",
        "errors_calculating",
        "last_error_at",
        "count",
        "version",
        "pending_version",
        "people",
        "groups",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Cohort

        return Cohort

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        from posthog.models import Action, Cohort

        cohort_ids = cls._extract_cohort_ids(resource.filters)
        action_ids = cls._extract_action_ids(resource.filters)

        edges: list[ResourceTransferEdge] = []
        edges.extend(build_edges_for_ids(cohort_ids, Cohort, "cohort", cls._rewrite_cohort_in_payload))
        edges.extend(build_edges_for_ids(action_ids, Action, "action", cls._rewrite_action_in_payload))
        return edges

    @classmethod
    def _rewrite_cohort_in_payload(cls, payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
        result = {**payload}
        if result.get("filters"):
            result["filters"] = cls._rewrite_cohort_id_in_filters(result["filters"], old_pk, new_pk)
        return result

    @classmethod
    def _rewrite_action_in_payload(cls, payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
        result = {**payload}
        if result.get("filters"):
            result["filters"] = cls._rewrite_action_id_in_filters(result["filters"], old_pk, new_pk)
        return result

    @classmethod
    def _extract_cohort_ids(cls, filters: dict | None) -> set[int]:
        """Extract cohort IDs from ``filters.properties`` where ``type == "cohort"``."""
        if not filters:
            return set()
        return collect_cohort_ids_from_properties(filters.get("properties"))

    @classmethod
    def _extract_action_ids(cls, filters: dict | None) -> set[int]:
        """Extract action IDs from behavioral filters where ``event_type == "actions"``.

        Covers both the primary ``key`` field and the secondary ``seq_event``
        field used by ``performed_event_sequence`` behavioral filters.
        """
        if not filters:
            return set()
        return cls._collect_action_ids_from_properties(filters.get("properties"))

    @classmethod
    def _collect_action_ids_from_properties(cls, properties: Any) -> set[int]:
        """Walk a (possibly nested) property-group structure and collect action IDs
        from behavioral property filters."""
        ids: set[int] = set()
        if isinstance(properties, list):
            for prop in properties:
                if isinstance(prop, dict) and prop.get("type") == "behavioral" and prop.get("event_type") == "actions":
                    if prop.get("key") is not None:
                        ids.add(int(prop["key"]))
                if isinstance(prop, dict) and prop.get("seq_event_type") == "actions":
                    if prop.get("seq_event") is not None:
                        ids.add(int(prop["seq_event"]))
        elif isinstance(properties, dict):
            for group in properties.get("values", []):
                if isinstance(group, dict):
                    ids.update(cls._collect_action_ids_from_properties(group.get("values", [])))
        return ids

    # --- rewriting JSON-embedded references ---

    @classmethod
    def _rewrite_cohort_id_in_filters(cls, filters: dict, old_pk: int, new_pk: int) -> dict:
        result = {**filters}
        if "properties" in result:
            result["properties"] = rewrite_cohort_id_in_properties(result["properties"], old_pk, new_pk)
        return result

    @classmethod
    def _rewrite_action_id_in_filters(cls, filters: dict, old_pk: int, new_pk: int) -> dict:
        result = {**filters}
        if "properties" in result:
            result["properties"] = cls._rewrite_action_id_in_properties(result["properties"], old_pk, new_pk)
        return result

    @classmethod
    def _rewrite_action_id_in_properties(cls, properties: Any, old_pk: int, new_pk: int) -> Any:
        """Walk a (possibly nested) property-group structure and rewrite action IDs
        in behavioral property filters."""
        if isinstance(properties, list):
            result = []
            for prop in properties:
                if not isinstance(prop, dict):
                    result.append(prop)
                    continue
                changed = {**prop}
                if (
                    changed.get("type") == "behavioral"
                    and changed.get("event_type") == "actions"
                    and changed.get("key") is not None
                    and int(changed["key"]) == old_pk
                ):
                    changed["key"] = new_pk
                if (
                    changed.get("seq_event_type") == "actions"
                    and changed.get("seq_event") is not None
                    and int(changed["seq_event"]) == old_pk
                ):
                    changed["seq_event"] = new_pk
                result.append(changed)
            return result
        elif isinstance(properties, dict):
            result_dict = {**properties}
            if "values" in result_dict:
                new_values = []
                for group in result_dict["values"]:
                    if isinstance(group, dict):
                        new_group = {**group}
                        if "values" in new_group:
                            new_group["values"] = cls._rewrite_action_id_in_properties(
                                new_group["values"], old_pk, new_pk
                            )
                        new_values.append(new_group)
                    else:
                        new_values.append(group)
                result_dict["values"] = new_values
            return result_dict
        return properties
