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

    Kept for backward compatibility during rollout.
    """

    def _fetch_filters() -> dict[int, list[dict[str, Any]]]:
        from products.llm_analytics.backend.models.clustering_config import ClusteringConfig

        configs = ClusteringConfig.objects.filter(team_id__in=inputs.team_ids).exclude(event_filters=[])
        return {config.team_id: config.event_filters for config in configs}

    return await asyncio.to_thread(_fetch_filters)


@dataclass
class JobConfig:
    """One clustering job's configuration, serializable over Temporal."""

    job_id: int
    name: str
    analysis_level: str
    event_filters: list[dict[str, Any]]


@dataclass
class FetchAllClusteringJobsInput:
    team_ids: list[int]


@activity.defn
async def fetch_all_clustering_jobs_activity(
    inputs: FetchAllClusteringJobsInput,
) -> dict[int, list[JobConfig]]:
    """Fetch enabled ClusteringJob rows for the given teams.

    Returns a dict mapping team_id to a list of JobConfig objects.
    Teams with no jobs are omitted from the result.
    """

    def _fetch_jobs() -> dict[int, list[JobConfig]]:
        from products.llm_analytics.backend.models.clustering_job import ClusteringJob

        jobs = ClusteringJob.objects.filter(team_id__in=inputs.team_ids, enabled=True).order_by("created_at")
        result: dict[int, list[JobConfig]] = {}
        for job in jobs:
            result.setdefault(job.team_id, []).append(
                JobConfig(
                    job_id=job.id,
                    name=job.name,
                    analysis_level=job.analysis_level,
                    event_filters=job.event_filters,
                )
            )
        return result

    return await asyncio.to_thread(_fetch_jobs)
