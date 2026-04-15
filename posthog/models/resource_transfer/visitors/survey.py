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


class SurveyVisitor(
    ResourceTransferVisitor,
    kind="Survey",
    excluded_fields=[
        "linked_flag",
        "targeting_flag",
        "internal_targeting_flag",
        "internal_response_sampling_flag",
        "headline_summary",
        "headline_response_count",
        "question_summaries",
    ],
    friendly_name="Survey",
):
    """
    TODO: When FeatureFlag duplication is supported in resource transfer, remove `linked_flag`
    from excluded_fields so the FK rewrites to the duplicated flag; then only strip
    linkedFlagVariant in adjust_duplicate_payload when the destination flag cannot satisfy that
    variant (substitution / validation).
    """

    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.surveys.backend.models import Survey

        return Survey

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        from posthog.models import Cohort

        cohort_ids = cls._extract_cohort_ids_from_conditions(resource.conditions)

        return build_edges_for_ids(cohort_ids, Cohort, "conditions_cohort", cls._rewrite_cohort_in_payload)

    @classmethod
    def _extract_cohort_ids_from_conditions(cls, conditions: dict | None) -> set[int]:
        if not conditions or not isinstance(conditions, dict):
            return set()
        ids: set[int] = set()
        if "properties" in conditions:
            ids.update(collect_cohort_ids_from_properties(conditions.get("properties")))
        return ids

    @classmethod
    def _rewrite_cohort_in_payload(cls, payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
        result = {**payload}
        cond = result.get("conditions")
        if isinstance(cond, dict) and "properties" in cond:
            result["conditions"] = {
                **cond,
                "properties": rewrite_cohort_id_in_properties(cond["properties"], old_pk, new_pk),
            }
        return result

    @classmethod
    def adjust_duplicate_payload(cls, payload: ResourcePayload, vertex: Any, new_team: Any) -> ResourcePayload:
        """Strip linkedFlagVariant; meaningless without a linked flag in the destination (see class TODO)."""
        result = {**payload}
        if result.get("conditions") and isinstance(result["conditions"], dict):
            cleaned = {**result["conditions"]}
            cleaned.pop("linkedFlagVariant", None)
            result["conditions"] = cleaned
        return result


class SurveyActionsThroughVisitor(
    ResourceTransferVisitor,
    kind="Survey_actions",
    user_facing=False,
    friendly_name="Survey action link",
):
    """
    Survey has a m2m relation with Actions using an auto-generated through model with the table name Survey_actions. There is no corresponding model in the code, so we need to hack this together.
    """

    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.surveys.backend.models import Survey

        return Survey._meta.get_field("actions").remote_field.through  # type: ignore
