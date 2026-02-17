"""Shared Temporal activities used by multiple llm_analytics workflows."""

import asyncio
from dataclasses import dataclass
from typing import Any

from temporalio import activity


@dataclass
class FetchAllClusteringFiltersInput:
    team_ids: list[int]


@activity.defn
async def fetch_all_clustering_filters_activity(
    inputs: FetchAllClusteringFiltersInput,
) -> dict[int, list[dict[str, Any]]]:
    """Fetch saved event filters from ClusteringConfig for the given teams.

    Used by both clustering and summarization coordinators to read
    user-configured filters at runtime.
    """

    def _fetch_filters() -> dict[int, list[dict[str, Any]]]:
        from products.llm_analytics.backend.models.clustering_config import ClusteringConfig

        configs = ClusteringConfig.objects.filter(team_id__in=inputs.team_ids).exclude(event_filters=[])
        return {config.team_id: config.event_filters for config in configs}

    return await asyncio.to_thread(_fetch_filters)
