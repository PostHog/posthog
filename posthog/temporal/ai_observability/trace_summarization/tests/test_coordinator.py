"""Tests for batch trace summarization coordinator workflow."""

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai_observability.shared_activities import (
    FetchAllClusteringFiltersInput,
    FetchAllClusteringJobsInput,
    JobConfig,
    resolve_level_jobs_for_team,
)
from posthog.temporal.ai_observability.team_discovery import TeamDiscoveryInput
from posthog.temporal.ai_observability.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_WINDOW_MINUTES,
    WORKFLOW_NAME,
)
from posthog.temporal.ai_observability.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
    _empty_summarization_results,
)
from posthog.temporal.ai_observability.trace_summarization.models import (
    BatchSummarizationInputs,
    BatchSummarizationMetrics,
    BatchSummarizationResult,
    CoordinatorResult,
)

from products.ai_observability.backend.summarization.models import SummarizationMode

SLOW_TEAM_ID = 1
DISCOVERED_TEAM_IDS = [SLOW_TEAM_ID, 2, 3, 4, 5]

child_runs: list[dict[str, Any]] = []


@workflow.defn(name=WORKFLOW_NAME)
class FakeTeamSummarizationWorkflow:
    @workflow.run
    async def run(self, inputs: BatchSummarizationInputs) -> BatchSummarizationResult:
        started = workflow.now()
        await workflow.sleep(timedelta(minutes=10 if inputs.team_id == SLOW_TEAM_ID else 1))
        if not workflow.unsafe.is_replaying():
            child_runs.append(
                {
                    "team_id": inputs.team_id,
                    "window": (inputs.window_start, inputs.window_end),
                    "started": started,
                    "finished": workflow.now(),
                }
            )
        return BatchSummarizationResult(
            batch_run_id=str(inputs.team_id), metrics=BatchSummarizationMetrics(items_queried=1, summaries_generated=1)
        )


@activity.defn(name="get_team_ids_for_llm_analytics")
async def fake_team_discovery(inputs: TeamDiscoveryInput | None = None) -> list[int]:
    return DISCOVERED_TEAM_IDS


@activity.defn(name="fetch_all_clustering_jobs_activity")
async def fake_fetch_jobs(inputs: FetchAllClusteringJobsInput) -> dict[int, list[JobConfig]]:
    return {}


@activity.defn(name="fetch_all_clustering_filters_activity")
async def fake_fetch_filters(inputs: FetchAllClusteringFiltersInput) -> dict[int, list[dict[str, Any]]]:
    return {}


async def _run_coordinator(inputs: BatchTraceSummarizationCoordinatorInputs) -> CoordinatorResult:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[BatchTraceSummarizationCoordinatorWorkflow, FakeTeamSummarizationWorkflow],
            activities=[fake_team_discovery, fake_fetch_jobs, fake_fetch_filters],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                BatchTraceSummarizationCoordinatorWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=55),
            )


def _max_overlap(runs: list[dict[str, Any]]) -> int:
    edges: list[tuple[datetime, int]] = [(r["started"], 1) for r in runs] + [(r["finished"], -1) for r in runs]
    running = peak = 0
    for _, delta in sorted(edges, key=lambda edge: (edge[0], edge[1])):
        running += delta
        peak = max(peak, running)
    return peak


class TestBatchTraceSummarizationCoordinatorWorkflow:
    """Tests for BatchTraceSummarizationCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=DEFAULT_MAX_ITEMS_PER_WINDOW,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["trace", "200"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="trace_level_with_max_traces",
            ),
            pytest.param(
                ["generation", "200"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="generation",
                    max_items=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="generation_level_with_max_traces",
            ),
            pytest.param(
                ["trace", "200", "20", "detailed", "30", "gpt-4.1-mini"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=200,
                    batch_size=20,
                    mode=SummarizationMode.DETAILED,
                    window_minutes=30,
                    model="gpt-4.1-mini",
                ),
                id="full_inputs",
            ),
        ],
    )
    def test_parse_inputs(self, inputs, expected):
        result = BatchTraceSummarizationCoordinatorWorkflow.parse_inputs(inputs)

        assert result.analysis_level == expected.analysis_level
        assert result.max_items == expected.max_items
        assert result.batch_size == expected.batch_size
        assert result.mode == expected.mode
        assert result.window_minutes == expected.window_minutes
        assert result.model == expected.model

    @pytest.mark.parametrize(
        "inputs,expected_message",
        [
            pytest.param(["trace", "200", "20", "bogus"], "minimal, detailed", id="unknown_mode"),
            pytest.param(["trace", "200", "20", "detailed", "30", "gpt-5.6-luna"], "gpt-4.1-nano", id="unknown_model"),
        ],
    )
    def test_parse_inputs_rejects_unknown_enum_value(self, inputs, expected_message):
        with pytest.raises(ValueError, match=expected_message):
            BatchTraceSummarizationCoordinatorWorkflow.parse_inputs(inputs)

    def test_continuation_fields_default_to_none(self):
        inputs = BatchTraceSummarizationCoordinatorInputs()

        assert inputs.remaining_team_ids is None
        assert inputs.per_team_filters is None
        assert inputs.results_so_far is None

    def test_continuation_fields_can_be_set(self):
        inputs = BatchTraceSummarizationCoordinatorInputs(
            remaining_team_ids=[100, 200, 300],
            per_team_filters={"100": [{"event": "$ai_generation"}]},
            results_so_far={
                "teams_succeeded": 5,
                "teams_failed": 1,
                "failed_team_ids": [99],
                "total_items": 50,
                "total_summaries": 40,
            },
        )

        assert inputs.remaining_team_ids == [100, 200, 300]
        assert inputs.per_team_filters == {"100": [{"event": "$ai_generation"}]}
        assert inputs.results_so_far is not None
        assert inputs.results_so_far["teams_succeeded"] == 5

    def test_empty_summarization_results(self):
        results = _empty_summarization_results()

        assert results == {
            "teams_succeeded": 0,
            "teams_failed": 0,
            "failed_team_ids": [],
            "total_items": 0,
            "total_summaries": 0,
        }

    def test_empty_results_returns_independent_instances(self):
        r1 = _empty_summarization_results()
        r2 = _empty_summarization_results()
        r1["failed_team_ids"].append(123)

        assert r2["failed_team_ids"] == []

    @pytest.mark.parametrize(
        "team_jobs,analysis_level,legacy_event_filters,expected_job_ids",
        [
            pytest.param(
                [],
                "trace",
                [{"event": "$ai_generation"}],
                [""],
                id="falls_back_to_legacy_when_no_jobs_exist",
            ),
            pytest.param(
                [
                    JobConfig(job_id="11", name="trace-job", analysis_level="trace", event_filters=[]),
                    JobConfig(job_id="22", name="gen-job", analysis_level="generation", event_filters=[]),
                ],
                "trace",
                [{"event": "$ai_generation"}],
                ["11"],
                id="uses_matching_jobs_when_present",
            ),
            pytest.param(
                [JobConfig(job_id="33", name="gen-job", analysis_level="generation", event_filters=[])],
                "trace",
                [{"event": "$ai_generation"}],
                [],
                id="skips_when_only_other_level_jobs_exist",
            ),
        ],
    )
    def test_resolve_level_jobs_for_team(self, team_jobs, analysis_level, legacy_event_filters, expected_job_ids):
        result = resolve_level_jobs_for_team(
            team_jobs=team_jobs,
            analysis_level=analysis_level,
            legacy_event_filters=legacy_event_filters,
        )

        assert [job.job_id for job in result] == expected_job_ids

    @pytest.mark.asyncio
    async def test_sliding_window_does_not_hold_teams_behind_a_slow_team(self):
        child_runs.clear()
        result = await _run_coordinator(BatchTraceSummarizationCoordinatorInputs(max_concurrent_teams=2))

        runs_by_team = {run["team_id"]: run for run in child_runs}
        assert result.teams_processed == len(DISCOVERED_TEAM_IDS)
        assert result.teams_failed == 0
        assert sorted(runs_by_team) == sorted(DISCOVERED_TEAM_IDS)
        assert _max_overlap(child_runs) == 2
        assert all(run["finished"] <= runs_by_team[SLOW_TEAM_ID]["finished"] for run in child_runs)
        windows = {run["window"] for run in child_runs}
        assert len(windows) == 1
        assert None not in next(iter(windows))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("max_concurrent_teams", [0, -1])
    async def test_non_positive_concurrency_fails_instead_of_hanging(self, max_concurrent_teams):
        child_runs.clear()
        with pytest.raises(WorkflowFailureError) as exc_info:
            await _run_coordinator(BatchTraceSummarizationCoordinatorInputs(max_concurrent_teams=max_concurrent_teams))

        assert isinstance(exc_info.value.cause, ApplicationError)
        assert "max_concurrent_teams" in str(exc_info.value.cause)
        assert child_runs == []
