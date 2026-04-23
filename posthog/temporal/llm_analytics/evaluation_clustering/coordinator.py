"""Coordinator for evaluation clustering Stage A (sampler).

The Stage B clustering coordinator lands alongside the clustering activities
in a follow-up PR; this module currently only owns the hourly sampler.
"""

import dataclasses
from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio import workflow
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    SAMPLER_CHILD_WORKFLOW_ID_PREFIX,
    SAMPLER_CHILD_WORKFLOW_RETRY_POLICY,
    SAMPLER_COORDINATOR_WORKFLOW_NAME,
    SAMPLER_DEFAULT_MAX_CONCURRENT_TEAMS,
    SAMPLER_WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.llm_analytics.evaluation_clustering.models import (
    SamplerCoordinatorResult,
    SamplerWorkflowInputs,
    SamplerWorkflowResult,
)
from posthog.temporal.llm_analytics.evaluation_clustering.workflow import LLMAEvaluationSamplerWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.coordinator_metrics import (
        increment_fetch_jobs_failed,
        increment_team_failed,
        increment_team_succeeded,
        record_jobs_dispatched,
        record_teams_discovered,
    )
    from posthog.temporal.llm_analytics.shared_activities import (
        FetchAllClusteringJobsInput,
        JobConfig,
        fetch_all_clustering_jobs_activity,
    )
    from posthog.temporal.llm_analytics.team_discovery import (
        DISCOVERY_ACTIVITY_RETRY_POLICY,
        DISCOVERY_ACTIVITY_TIMEOUT,
        GUARANTEED_TEAM_IDS,
        SAMPLE_PERCENTAGE,
        TeamDiscoveryInput,
        get_team_ids_for_llm_analytics,
    )

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class SamplerCoordinatorInputs:
    """Inputs for the evaluation sampler coordinator.

    The clustering coordinator (Stage B) reuses an identical shape but lives in
    a follow-up PR — the dataclass split is preserved there so the two
    coordinators stay independent.
    """

    max_concurrent_teams: int = SAMPLER_DEFAULT_MAX_CONCURRENT_TEAMS
    # continue_as_new carry-state
    remaining_team_ids: list[int] | None = None
    per_team_jobs: dict[str, list[dict[str, Any]]] | None = None
    results_so_far: dict[str, Any] | None = None


def _empty_results() -> dict[str, Any]:
    return {
        "jobs_dispatched": 0,
        "jobs_succeeded": 0,
        "jobs_failed": 0,
        "total_sampled": 0,
        "total_embedded": 0,
    }


async def _discover_teams_and_jobs() -> tuple[list[int], dict[int, list[JobConfig]]]:
    """Team discovery + fetch all clustering jobs, reusing the shared LLMA activities."""
    try:
        team_ids = await workflow.execute_activity(
            get_team_ids_for_llm_analytics,
            TeamDiscoveryInput(sample_percentage=SAMPLE_PERCENTAGE),
            start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
            retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
        )
    except Exception:
        logger.warning("Team discovery failed, falling back to guaranteed teams", exc_info=True)
        team_ids = sorted(GUARANTEED_TEAM_IDS)

    per_team_jobs: dict[int, list[JobConfig]] = {}
    try:
        per_team_jobs = await workflow.execute_activity(
            fetch_all_clustering_jobs_activity,
            FetchAllClusteringJobsInput(team_ids=team_ids),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except Exception:
        logger.warning("fetch_all_clustering_jobs_activity failed; proceeding with no jobs", exc_info=True)
        increment_fetch_jobs_failed("eval_sampling", "evaluation")

    return team_ids, per_team_jobs


def _evaluation_jobs_for_team(team_jobs: list[JobConfig]) -> list[JobConfig]:
    """Pick the evaluation-level jobs for a team.

    Unlike trace/generation where the coordinator falls back to a legacy filter config
    when the team has no ClusteringJob rows, evaluation clustering is opt-in —
    if there's no evaluation-level job for the team, we skip it entirely.
    """
    return [job for job in team_jobs if job.analysis_level == "evaluation"]


@workflow.defn(name=SAMPLER_COORDINATOR_WORKFLOW_NAME)
class LLMAEvaluationSamplerCoordinatorWorkflow(PostHogWorkflow):
    """Hourly coordinator that spawns a sampler workflow per (team, eval job).

    Uses continue_as_new to keep history bounded across many teams.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SamplerCoordinatorInputs:
        return SamplerCoordinatorInputs(
            max_concurrent_teams=int(inputs[0]) if inputs else SAMPLER_DEFAULT_MAX_CONCURRENT_TEAMS,
        )

    @workflow.run
    async def run(self, inputs: SamplerCoordinatorInputs) -> SamplerCoordinatorResult:
        if inputs.remaining_team_ids is not None:
            team_ids = inputs.remaining_team_ids
            per_team_jobs: dict[int, list[JobConfig]] = {}
            if inputs.per_team_jobs:
                for k, job_dicts in inputs.per_team_jobs.items():
                    per_team_jobs[int(k)] = [JobConfig(**jd) for jd in job_dicts]
            results_so_far = inputs.results_so_far or _empty_results()
        else:
            logger.info("Starting evaluation sampler coordinator")
            team_ids, per_team_jobs = await _discover_teams_and_jobs()
            record_teams_discovered(len(team_ids), "eval_sampling", "evaluation")
            results_so_far = _empty_results()

        max_concurrent = inputs.max_concurrent_teams
        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            handles: list[
                tuple[int, str, ChildWorkflowHandle[LLMAEvaluationSamplerWorkflow, SamplerWorkflowResult]]
            ] = []
            for team_id in batch:
                for job in _evaluation_jobs_for_team(per_team_jobs.get(team_id, [])):
                    handle = await workflow.start_child_workflow(
                        LLMAEvaluationSamplerWorkflow.run,
                        SamplerWorkflowInputs(
                            team_id=team_id,
                            job_id=job.job_id,
                            job_name=job.name,
                            event_filters=job.event_filters,
                        ),
                        id=(f"{SAMPLER_CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{job.job_id}-{workflow.now().isoformat()}"),
                        execution_timeout=SAMPLER_WORKFLOW_EXECUTION_TIMEOUT,
                        retry_policy=SAMPLER_CHILD_WORKFLOW_RETRY_POLICY,
                        parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
                    )
                    handles.append((team_id, job.job_id, handle))

            if handles:
                record_jobs_dispatched(len(handles), "eval_sampling", "evaluation")
                results_so_far["jobs_dispatched"] += len(handles)

            for team_id, job_id, handle in handles:
                try:
                    res: SamplerWorkflowResult = await handle
                    results_so_far["jobs_succeeded"] += 1
                    results_so_far["total_sampled"] += res.sampled
                    results_so_far["total_embedded"] += res.embedded
                    increment_team_succeeded("eval_sampling", "evaluation")
                except Exception:
                    logger.exception("eval sampler child failed", team_id=team_id, job_id=job_id)
                    results_so_far["jobs_failed"] += 1
                    increment_team_failed("eval_sampling", "evaluation")

            remaining = team_ids[batch_start + max_concurrent :]
            if remaining and workflow.info().is_continue_as_new_suggested():
                serializable_jobs = {str(k): [dataclasses.asdict(j) for j in v] for k, v in per_team_jobs.items()}
                workflow.continue_as_new(
                    SamplerCoordinatorInputs(
                        max_concurrent_teams=inputs.max_concurrent_teams,
                        remaining_team_ids=remaining,
                        per_team_jobs=serializable_jobs,
                        results_so_far=results_so_far,
                    )
                )

        logger.info(
            "evaluation sampler coordinator completed",
            **results_so_far,
        )
        return SamplerCoordinatorResult(
            jobs_dispatched=results_so_far["jobs_dispatched"],
            jobs_succeeded=results_so_far["jobs_succeeded"],
            jobs_failed=results_so_far["jobs_failed"],
            total_sampled=results_so_far["total_sampled"],
            total_embedded=results_so_far["total_embedded"],
        )
