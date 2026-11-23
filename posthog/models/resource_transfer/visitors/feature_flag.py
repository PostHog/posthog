from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models

from posthog.models.resource_transfer.registered_models import registered_model
from posthog.models.resource_transfer.types import ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import build_edges_for_ids, make_json_id_rewriter
from posthog.models.resource_transfer.visitors.feature_flag_filters import (
    collect_action_ids_from_flag_filters,
    collect_cohort_ids_from_flag_filters,
    get_holdout_id_from_flag_filters,
    rewrite_action_in_flag_payload,
    rewrite_cohort_in_flag_payload,
    rewrite_holdout_in_flag_payload,
)

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.reserved_variant_keys import (
    non_string_variants,
    reserved_variant_key,
    reserved_variant_key_message,
)

if TYPE_CHECKING:
    from posthog.models import Team
    from posthog.models.resource_transfer.types import ResourceTransferVertex


class FeatureFlagVisitor(
    ResourceTransferVisitor,
    kind="FeatureFlag",
    excluded_fields=[
        "usage_dashboard",
        "analytics_dashboards",
        "last_called_at",
        "deleted",
        "_evaluation_tag_names",
    ],
    friendly_name="Feature flag",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.feature_flags.backend.models.feature_flag import FeatureFlag

        return FeatureFlag

    @classmethod
    def adjust_duplicate_payload(
        cls, payload: ResourcePayload, vertex: ResourceTransferVertex, new_team: Team
    ) -> ResourcePayload:
        # A copy creates a new flag in the destination project, so no variant key is held there yet.
        filters = payload.get("filters")
        # FeatureFlag.save() refuses these with Django's ValidationError. The transfer view returns a 500 for that error.
        if unkeyed := non_string_variants(filters):
            raise ValueError(f"{unkeyed[0][0]} must be a string.")
        reserved_key = reserved_variant_key(filters)
        if reserved_key is not None:
            raise ValueError(reserved_variant_key_message(reserved_key))
        return super().adjust_duplicate_payload(payload, vertex, new_team)

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        return str(resource.key) if getattr(resource, "key", None) else super().get_display_name(resource)

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        filters = resource.filters or {}
        cohort_ids = collect_cohort_ids_from_flag_filters(filters)
        action_ids = collect_action_ids_from_flag_filters(filters)

        edges: list[ResourceTransferEdge] = []
        edges.extend(build_edges_for_ids(cohort_ids, Cohort, "cohort", rewrite_cohort_in_flag_payload))
        edges.extend(
            build_edges_for_ids(action_ids, registered_model("Action"), "action", rewrite_action_in_flag_payload)
        )

        holdout_id = get_holdout_id_from_flag_filters(filters)
        if holdout_id is not None:
            holdout_model = registered_model("ExperimentHoldout")
            edges.append(
                ResourceTransferEdge(
                    name=f"holdout:{holdout_id}",
                    target_model=holdout_model,
                    target_primary_key=holdout_id,
                    rewrite_relation=make_json_id_rewriter(holdout_model, holdout_id, rewrite_holdout_in_flag_payload),
                )
            )

        return edges
