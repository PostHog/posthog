"""
Coordinator workflow for batch trace summarization.

This workflow discovers teams dynamically via the team discovery activity
and spawns child workflows to process traces for each team.

Uses continue_as_new between teams, when Temporal suggests it, to keep the
workflow history bounded (Temporal has a 50K event limit per execution).

Per-team child workflows handle the case where a team has no traces
gracefully (returning empty results).

Teams are processed through a sliding window: up to max_concurrent_teams
children (default 20) run at once, and the next team starts as soon as any
child finishes. Every child in one run summarizes the same time window,
fixed from the time Temporal started the run.
"""

import asyncio
import dataclasses
from datetime import datetime, timedelta
from typing import Any

import structlog
import temporalio
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.ai_observability.trace_summarization import constants
from posthog.temporal.ai_observability.trace_summarization.constants import (
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_CONCURRENT_TEAMS,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_WINDOW_MINUTES,
    DEFAULT_WINDOW_OFFSET_MINUTES,
    GENERATION_CHILD_WORKFLOW_ID_PREFIX,
    SLIDING_WINDOW_PATCH_ID,
    WORKFLOW_EXECUTION_TIMEOUT_MINUTES,
)
from posthog.temporal.ai_observability.trace_summarization.models import (
    AnalysisLevel,
    BatchSummarizationInputs,
    BatchSummarizationResult,
    CoordinatorResult,
)
from posthog.temporal.ai_observability.trace_summarization.workflow import BatchTraceSummarizationWorkflow
from posthog.temporal.common.base import PostHogWorkflow

from products.ai_observability.backend.summarization.models import OpenAIModel, SummarizationMode

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.ai_observability.coordinator_metrics import (
        increment_team_failed,
        increment_team_succeeded,
        record_jobs_dispatched,
        record_teams_discovered,
    )
    from posthog.temporal.ai_observability.shared_activities import (
        FetchAllClusteringFiltersInput,
        FetchAllClusteringJobsInput,
        JobConfig,
        fetch_all_clustering_filters_activity,
        fetch_all_clustering_jobs_activity,
        resolve_level_jobs_for_team,
    )
    from posthog.temporal.ai_observability.team_discovery import (
        DISCOVERY_ACTIVITY_RETRY_POLICY,
        DISCOVERY_ACTIVITY_TIMEOUT,
        DISCOVERY_FAIL_CLOSED_PATCH_ID,
        GUARANTEED_TEAM_IDS,
        TeamDiscoveryInput,
        get_team_ids_for_ai_observability,
    )

logger = structlog.get_logger(__name__)


def _summarization_window(run_start: datetime, window_minutes: int) -> tuple[str, str]:
    """The window every child of a run summarizes, offset so traces have time to complete."""
    window_end = run_start - timedelta(minutes=DEFAULT_WINDOW_OFFSET_MINUTES)
    window_start = window_end - timedelta(minutes=window_minutes)
    return window_start.strftime("%Y-%m-%dT%H:%M:%SZ"), window_end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_summarization_results() -> dict[str, Any]:
    return {
        "teams_succeeded": 0,
        "teams_failed": 0,
        "failed_team_ids": [],
        "total_items": 0,
        "total_summaries": 0,
    }


@dataclasses.dataclass
class BatchTraceSummarizationCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    analysis_level: AnalysisLevel = "trace"  # "trace" or "generation"
    max_items: int = DEFAULT_MAX_ITEMS_PER_WINDOW
    batch_size: int = DEFAULT_BATCH_SIZE
    mode: SummarizationMode = DEFAULT_MODE
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    model: str = DEFAULT_MODEL
    max_concurrent_teams: int = DEFAULT_MAX_CONCURRENT_TEAMS
    # Fields used by continue_as_new to carry state across continuations.
    # When remaining_team_ids is set, team discovery is skipped.
    remaining_team_ids: list[int] | None = None
    per_team_filters: dict[str, list[dict[str, Any]]] | None = None
    per_team_jobs: dict[str, list[dict[str, Any]]] | None = None
    results_so_far: dict[str, Any] | None = None
    window_start: str | None = None
    window_end: str | None = None


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class BatchTraceSummarizationCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that discovers teams dynamically and spawns child
    workflows for each team. Teams with no traces will complete quickly
    with empty results.

    Uses continue_as_new to keep history bounded when processing many teams.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchTraceSummarizationCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return BatchTraceSummarizationCoordinatorInputs(
            analysis_level="generation" if len(inputs) > 0 and inputs[0] == "generation" else "trace",
            max_items=int(inputs[1]) if len(inputs) > 1 else DEFAULT_MAX_ITEMS_PER_WINDOW,
            batch_size=int(inputs[2]) if len(inputs) > 2 else DEFAULT_BATCH_SIZE,
            mode=SummarizationMode.parse(inputs[3]) if len(inputs) > 3 else DEFAULT_MODE,
            window_minutes=int(inputs[4]) if len(inputs) > 4 else DEFAULT_WINDOW_MINUTES,
            model=OpenAIModel.parse(inputs[5]) if len(inputs) > 5 else DEFAULT_MODEL,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BatchTraceSummarizationCoordinatorInputs) -> CoordinatorResult:
        """Execute coordinator workflow."""

        # Phase A: resolve teams and filters.
        # On continuation legs, these are passed in directly to avoid
        # re-running expensive ClickHouse queries.
        if inputs.remaining_team_ids is not None:
            team_ids = inputs.remaining_team_ids
            # Temporal JSON serialization converts int dict keys to strings
            per_team_filters: dict[int, list[dict[str, Any]]] = (
                {int(k): v for k, v in inputs.per_team_filters.items()} if inputs.per_team_filters else {}
            )
            per_team_jobs: dict[int, list[JobConfig]] = {}
            if inputs.per_team_jobs:
                for k, job_dicts in inputs.per_team_jobs.items():
                    per_team_jobs[int(k)] = [JobConfig(**jd) for jd in job_dicts]
            results_so_far = inputs.results_so_far or _empty_summarization_results()
            logger.info(
                "Resuming summarization coordinator after continue_as_new",
                remaining_teams=len(team_ids),
                teams_succeeded_so_far=results_so_far["teams_succeeded"],
            )
        else:
            logger.info(
                "Starting batch trace summarization coordinator",
                analysis_level=inputs.analysis_level,
                max_items=inputs.max_items,
                window_minutes=inputs.window_minutes,
            )

            try:
                team_ids = await temporalio.workflow.execute_activity(
                    get_team_ids_for_ai_observability,
                    TeamDiscoveryInput(),
                    start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                    retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
                )
            except Exception:
                if temporalio.workflow.patched(DISCOVERY_FAIL_CLOSED_PATCH_ID):
                    raise
                logger.warning("Team discovery activity failed, falling back to guaranteed teams", exc_info=True)
                team_ids = sorted(GUARANTEED_TEAM_IDS)

            logger.info("Processing discovered teams", team_count=len(team_ids), team_ids=team_ids)
            record_teams_discovered(len(team_ids), "summarization", inputs.analysis_level)

            # Fetch clustering jobs for all teams
            per_team_jobs = {}
            try:
                per_team_jobs = await temporalio.workflow.execute_activity(
                    fetch_all_clustering_jobs_activity,
                    FetchAllClusteringJobsInput(team_ids=team_ids),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
                )
            except Exception:
                logger.warning("Failed to fetch clustering jobs, falling back to filters", exc_info=True)

            # Always fetch legacy filters — used for teams without jobs
            per_team_filters = {}
            try:
                per_team_filters = await temporalio.workflow.execute_activity(
                    fetch_all_clustering_filters_activity,
                    FetchAllClusteringFiltersInput(team_ids=team_ids),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
                )
            except Exception:
                logger.warning("Failed to fetch clustering filters, proceeding without filters", exc_info=True)

            results_so_far = _empty_summarization_results()

        # Phase B: dispatch the teams, using continue_as_new to keep the
        # workflow history bounded.
        child_id_prefix = (
            GENERATION_CHILD_WORKFLOW_ID_PREFIX if inputs.analysis_level == "generation" else CHILD_WORKFLOW_ID_PREFIX
        )

        if temporalio.workflow.patched(SLIDING_WINDOW_PATCH_ID):
            # With no slot the dispatch loop would wait forever without starting a child.
            if inputs.max_concurrent_teams < 1:
                raise ApplicationError(
                    f"max_concurrent_teams must be at least 1, got {inputs.max_concurrent_teams}",
                    non_retryable=True,
                )
            if not (inputs.window_start and inputs.window_end):
                # workflow_start_time, not start_time: a worker can pick the run up late, for
                # example during a deploy, and that must not shift the hour the run covers.
                window_start, window_end = _summarization_window(
                    temporalio.workflow.info().workflow_start_time, inputs.window_minutes
                )
                inputs = dataclasses.replace(inputs, window_start=window_start, window_end=window_end)
            await self._dispatch_sliding_window(
                inputs, team_ids, per_team_jobs, per_team_filters, results_so_far, child_id_prefix
            )
        else:
            await self._dispatch_batches(
                inputs, team_ids, per_team_jobs, per_team_filters, results_so_far, child_id_prefix
            )

        # Final leg: return accumulated results
        total_teams = results_so_far["teams_succeeded"] + results_so_far["teams_failed"]
        logger.info(
            "Batch trace summarization coordinator completed",
            teams_processed=total_teams,
            teams_succeeded=results_so_far["teams_succeeded"],
            teams_failed=results_so_far["teams_failed"],
            total_items=results_so_far["total_items"],
            total_summaries=results_so_far["total_summaries"],
        )

        return CoordinatorResult(
            teams_processed=total_teams,
            teams_failed=results_so_far["teams_failed"],
            failed_team_ids=results_so_far["failed_team_ids"],
            total_items=results_so_far["total_items"],
            total_summaries=results_so_far["total_summaries"],
        )

    async def _dispatch_sliding_window(
        self,
        inputs: BatchTraceSummarizationCoordinatorInputs,
        team_ids: list[int],
        per_team_jobs: dict[int, list[JobConfig]],
        per_team_filters: dict[int, list[dict[str, Any]]],
        results_so_far: dict[str, Any],
        child_id_prefix: str,
    ) -> None:
        """Keep up to max_concurrent_teams children running, so one slow team holds one slot only."""
        in_flight = 0
        pending: list[asyncio.Task[None]] = []

        async def collect(
            team_id: int, handle: ChildWorkflowHandle[BatchTraceSummarizationWorkflow, BatchSummarizationResult]
        ) -> None:
            nonlocal in_flight
            try:
                await self._collect_child_result(team_id, handle, results_so_far, inputs.analysis_level)
            finally:
                in_flight -= 1

        def has_free_slot() -> bool:
            return in_flight < inputs.max_concurrent_teams

        def is_drained() -> bool:
            return in_flight == 0

        for index, team_id in enumerate(team_ids):
            if index > 0 and temporalio.workflow.info().is_continue_as_new_suggested():
                # Children close with this run, so let the running ones finish first.
                await temporalio.workflow.wait_condition(is_drained)
                logger.info(
                    "Continuing as new to keep history bounded",
                    teams_remaining=len(team_ids) - index,
                    teams_processed_this_leg=index,
                )
                self._continue_as_new(inputs, team_ids[index:], per_team_jobs, per_team_filters, results_so_far)

            level_jobs = self._level_jobs(inputs, team_id, per_team_jobs, per_team_filters)
            for job in level_jobs:
                await temporalio.workflow.wait_condition(has_free_slot)
                handle = await self._start_child(inputs, team_id, job, child_id_prefix)
                in_flight += 1
                record_jobs_dispatched(1, "summarization", inputs.analysis_level)
                pending.append(asyncio.create_task(collect(team_id, handle)))

        await asyncio.gather(*pending)

    async def _dispatch_batches(
        self,
        inputs: BatchTraceSummarizationCoordinatorInputs,
        team_ids: list[int],
        per_team_jobs: dict[int, list[JobConfig]],
        per_team_filters: dict[int, list[dict[str, Any]]],
        results_so_far: dict[str, Any],
        child_id_prefix: str,
    ) -> None:
        """Process fixed batches of teams. Only replays executions that started before the sliding window."""
        max_concurrent = inputs.max_concurrent_teams
        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[
                tuple[int, ChildWorkflowHandle[BatchTraceSummarizationWorkflow, BatchSummarizationResult]]
            ] = []
            for team_id in batch:
                for job in self._level_jobs(inputs, team_id, per_team_jobs, per_team_filters):
                    handle = await self._start_child(inputs, team_id, job, child_id_prefix)
                    workflow_handles.append((team_id, handle))

            if workflow_handles:
                record_jobs_dispatched(len(workflow_handles), "summarization", inputs.analysis_level)

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                await self._collect_child_result(team_id, handle, results_so_far, inputs.analysis_level)

            # After each batch, check if Temporal suggests continuing as new
            # to keep the history size bounded.
            remaining = team_ids[batch_start + max_concurrent :]
            if remaining and temporalio.workflow.info().is_continue_as_new_suggested():
                logger.info(
                    "Continuing as new to keep history bounded",
                    teams_remaining=len(remaining),
                    teams_processed_this_leg=batch_start + len(batch),
                )
                self._continue_as_new(inputs, remaining, per_team_jobs, per_team_filters, results_so_far)

    @staticmethod
    def _level_jobs(
        inputs: BatchTraceSummarizationCoordinatorInputs,
        team_id: int,
        per_team_jobs: dict[int, list[JobConfig]],
        per_team_filters: dict[int, list[dict[str, Any]]],
    ) -> list[JobConfig]:
        level_jobs = resolve_level_jobs_for_team(
            team_jobs=per_team_jobs.get(team_id, []),
            analysis_level=inputs.analysis_level,
            legacy_event_filters=per_team_filters.get(team_id, []),
        )
        if not level_jobs:
            logger.info(
                "Skipping team for analysis level with no matching summarization jobs",
                team_id=team_id,
                analysis_level=inputs.analysis_level,
            )
        return level_jobs

    @staticmethod
    async def _start_child(
        inputs: BatchTraceSummarizationCoordinatorInputs,
        team_id: int,
        job: JobConfig,
        child_id_prefix: str,
    ) -> ChildWorkflowHandle[BatchTraceSummarizationWorkflow, BatchSummarizationResult]:
        child_suffix = f"-{team_id}-{job.job_id}" if job.job_id else f"-{team_id}"
        return await temporalio.workflow.start_child_workflow(
            BatchTraceSummarizationWorkflow.run,
            BatchSummarizationInputs(
                team_id=team_id,
                analysis_level=inputs.analysis_level,
                max_items=inputs.max_items,
                batch_size=inputs.batch_size,
                mode=inputs.mode,
                window_minutes=inputs.window_minutes,
                model=inputs.model,
                window_start=inputs.window_start,
                window_end=inputs.window_end,
                event_filters=job.event_filters,
                job_id=job.job_id,
                job_name=job.name,
            ),
            id=f"{child_id_prefix}{child_suffix}-{temporalio.workflow.now().isoformat()}",
            execution_timeout=timedelta(minutes=WORKFLOW_EXECUTION_TIMEOUT_MINUTES),
            retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.TERMINATE,
        )

    @staticmethod
    async def _collect_child_result(
        team_id: int,
        handle: ChildWorkflowHandle[BatchTraceSummarizationWorkflow, BatchSummarizationResult],
        results_so_far: dict[str, Any],
        analysis_level: AnalysisLevel,
    ) -> None:
        try:
            workflow_result: BatchSummarizationResult = await handle
            results_so_far["total_items"] += workflow_result.metrics.items_queried
            results_so_far["total_summaries"] += workflow_result.metrics.summaries_generated
            results_so_far["teams_succeeded"] += 1
            increment_team_succeeded("summarization", analysis_level)

        except Exception:
            logger.exception("Failed to process team", team_id=team_id)
            results_so_far["failed_team_ids"].append(team_id)
            results_so_far["teams_failed"] += 1
            increment_team_failed("summarization", analysis_level)

    @staticmethod
    def _continue_as_new(
        inputs: BatchTraceSummarizationCoordinatorInputs,
        remaining: list[int],
        per_team_jobs: dict[int, list[JobConfig]],
        per_team_filters: dict[int, list[dict[str, Any]]],
        results_so_far: dict[str, Any],
    ) -> None:
        # Serialize for Temporal JSON (string keys)
        serializable_filters = {str(k): v for k, v in per_team_filters.items()}
        serializable_jobs = {str(k): [dataclasses.asdict(j) for j in v] for k, v in per_team_jobs.items()}
        temporalio.workflow.continue_as_new(
            dataclasses.replace(
                inputs,
                remaining_team_ids=remaining,
                per_team_filters=serializable_filters,
                per_team_jobs=serializable_jobs,
                results_so_far=results_so_far,
            )
        )
