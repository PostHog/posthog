"""Shared Temporal activities used by multiple llm_analytics workflows."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, cast

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.ai_observability.backend.facade.evaluation_runtime import consented_team_ids

AnalysisLevel = Literal["trace", "generation", "evaluation"]
CLUSTERING_OPT_IN_PATCH_ID = "ai-observability-clustering-opt-in"


def enabled_clustering_team_ids(team_ids: list[int] | None = None) -> set[int]:
    from products.ai_observability.backend.models.clustering_config import (  # noqa: PLC0415 - keeps Django models off the workflow import path
        ClusteringConfig,
    )

    configs = ClusteringConfig.objects.filter(enabled=True)
    if team_ids is not None:
        configs = configs.filter(team_id__in=team_ids)
    return set(configs.values_list("team_id", flat=True))


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
        from products.ai_observability.backend.models.clustering_config import ClusteringConfig

        configs = ClusteringConfig.objects.filter(team_id__in=inputs.team_ids).exclude(event_filters=[])
        return {config.team_id: config.event_filters for config in configs}

    return await asyncio.to_thread(_fetch_filters)


@frozen
class TeamAIConsentInput:
    team_id: int


@activity.defn
async def check_ai_data_processing_consent_activity(inputs: TeamAIConsentInput) -> bool:
    """Require both clustering opt-in and organization AI data processing approval."""
    consented = await database_sync_to_async_pool(consented_team_ids)([inputs.team_id])
    enabled = await database_sync_to_async_pool(enabled_clustering_team_ids)([inputs.team_id])
    return inputs.team_id in consented and inputs.team_id in enabled


@dataclass
class JobConfig:
    """One clustering job's configuration, serializable over Temporal."""

    job_id: str
    name: str
    analysis_level: AnalysisLevel
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
        from products.ai_observability.backend.models.clustering_job import ClusteringJob
        from products.ai_observability.backend.models.clustering_run import ACTIVE_CLUSTERING_RUN_STATUSES

        jobs = (
            ClusteringJob.objects.filter(
                team_id__in=inputs.team_ids, enabled=True, team__clustering_config__enabled=True
            )
            .exclude(first_runs__status__in=ACTIVE_CLUSTERING_RUN_STATUSES)
            .order_by("created_at")
        )
        result: dict[int, list[JobConfig]] = {}
        for job in jobs:
            result.setdefault(job.team_id, []).append(
                JobConfig(
                    job_id=str(job.id),
                    name=job.name,
                    analysis_level=cast(AnalysisLevel, job.analysis_level),
                    event_filters=job.event_filters,
                )
            )
        return result

    return await asyncio.to_thread(_fetch_jobs)


def resolve_level_jobs_for_team(
    team_jobs: list[JobConfig],
    analysis_level: AnalysisLevel,
    legacy_event_filters: list[dict[str, Any]],
    allow_legacy_fallback: bool = True,
) -> list[JobConfig]:
    """Pick jobs matching the analysis level, with legacy fallback.

    If the team has ClusteringJob rows but none for this level, returns [].
    If the team has no rows at all, returns a single legacy JobConfig(job_id="").
    """
    level_jobs = [job for job in team_jobs if job.analysis_level == analysis_level]
    if level_jobs:
        return level_jobs

    if team_jobs or not allow_legacy_fallback:
        return []

    return [JobConfig(job_id="", name="", analysis_level=analysis_level, event_filters=legacy_event_filters)]
