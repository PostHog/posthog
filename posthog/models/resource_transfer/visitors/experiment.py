from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models import Action, Cohort
from posthog.models.resource_transfer.types import ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import build_edges_for_ids
from posthog.models.resource_transfer.visitors.experiment_payload import (
    collect_cohort_and_action_ids_from_experiment_json,
    rewrite_action_in_experiment_payload,
    rewrite_cohort_in_experiment_payload,
)


class ExperimentVisitor(
    ResourceTransferVisitor,
    kind="Experiment",
    excluded_fields=[
        "start_date",
        "end_date",
        "archived",
        "deleted",
        "status",
        "conclusion",
        "conclusion_comment",
        "created_at",
        "updated_at",
    ],
    friendly_name="Experiment",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.experiments.backend.models.experiment import Experiment

        return Experiment

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        cohort_ids, action_ids = collect_cohort_and_action_ids_from_experiment_json(resource)

        edges: list[ResourceTransferEdge] = []
        edges.extend(build_edges_for_ids(cohort_ids, Cohort, "json_cohort", rewrite_cohort_in_experiment_payload))
        edges.extend(build_edges_for_ids(action_ids, Action, "json_action", rewrite_action_in_experiment_payload))
        return edges
