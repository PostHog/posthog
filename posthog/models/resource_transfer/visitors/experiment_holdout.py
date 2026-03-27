from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models import Cohort
from posthog.models.resource_transfer.types import ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import (
    build_edges_for_ids,
    collect_cohort_ids_from_properties,
    rewrite_cohort_id_in_properties,
)


class ExperimentHoldoutVisitor(
    ResourceTransferVisitor,
    kind="ExperimentHoldout",
    excluded_fields=["created_at", "updated_at"],
    friendly_name="Experiment holdout",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.experiments.backend.models.experiment import ExperimentHoldout

        return ExperimentHoldout

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        cohort_ids: set[int] = set()
        for entry in resource.filters or []:
            if isinstance(entry, dict):
                cohort_ids.update(collect_cohort_ids_from_properties(entry.get("properties")))

        return build_edges_for_ids(cohort_ids, Cohort, "cohort", _rewrite_cohort_in_holdout_payload)


def _rewrite_cohort_in_holdout_payload(payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
    result = {**payload}
    if result.get("filters") is not None:
        new_filters = []
        for entry in result["filters"]:
            if isinstance(entry, dict) and entry.get("properties") is not None:
                new_filters.append(
                    {
                        **entry,
                        "properties": rewrite_cohort_id_in_properties(entry["properties"], int(old_pk), int(new_pk)),
                    }
                )
            else:
                new_filters.append(entry)
        result["filters"] = new_filters
    return result
