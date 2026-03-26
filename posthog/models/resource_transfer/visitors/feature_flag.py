from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models import Action, Cohort
from posthog.models.resource_transfer.types import ResourceTransferEdge
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

from products.experiments.backend.models.experiment import ExperimentHoldout


class FeatureFlagVisitor(
    ResourceTransferVisitor,
    kind="FeatureFlag",
    excluded_fields=[
        "usage_dashboard",
        "analytics_dashboards",
        "last_called_at",
        "deleted",
        "rollback_conditions",
        "performed_rollback",
        "_evaluation_tag_names",
    ],
    friendly_name="Feature flag",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models.feature_flag import FeatureFlag

        return FeatureFlag

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
        edges.extend(build_edges_for_ids(action_ids, Action, "action", rewrite_action_in_flag_payload))

        holdout_id = get_holdout_id_from_flag_filters(filters)
        if holdout_id is not None:
            edges.append(
                ResourceTransferEdge(
                    name=f"holdout:{holdout_id}",
                    target_model=ExperimentHoldout,
                    target_primary_key=holdout_id,
                    rewrite_relation=make_json_id_rewriter(
                        ExperimentHoldout, holdout_id, rewrite_holdout_in_flag_payload
                    ),
                )
            )

        return edges
