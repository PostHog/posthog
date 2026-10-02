import uuid
import asyncio

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.experiments.models import (
    ExperimentSavedMetricInput,
    ExperimentSavedMetricResult,
    ExperimentSavedMetricsWorkflowInputs,
    MetricsPageInput,
    SavedMetricsPage,
)
from posthog.temporal.experiments.workflows import ExperimentSavedMetricsWorkflow, _record_publish_outcome

FAST_EXPERIMENT = 101
SLOW_EXPERIMENT = 102


def _single_page(metrics: list[ExperimentSavedMetricInput]):
    @activity.defn(name="get_experiment_saved_metrics_page")
    async def mock_discover(inputs: MetricsPageInput) -> SavedMetricsPage:
        return SavedMetricsPage(metrics=metrics, next_after_experiment_id=None)

    return mock_discover


async def _run_workflow(activities: list) -> dict:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ExperimentSavedMetricsWorkflow],
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ExperimentSavedMetricsWorkflow.run,
                ExperimentSavedMetricsWorkflowInputs(hour=2),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
async def test_an_experiment_publishes_before_the_whole_batch_finishes():
    """A slow experiment must not delay another experiment's publish. The slow experiment's metric only
    completes after the fast experiment's publish activity ran, so a workflow that publishes behind a
    whole-batch barrier fails this test (the fast publish then cannot run until the slow metric ends)."""
    fast_published = asyncio.Event()
    publish_calls: list[int] = []

    mock_discover = _single_page(
        [
            ExperimentSavedMetricInput(
                experiment_id=FAST_EXPERIMENT, metric_uuid="m-fast", fingerprint="f1", team_id=1
            ),
            ExperimentSavedMetricInput(
                experiment_id=SLOW_EXPERIMENT, metric_uuid="m-slow", fingerprint="f2", team_id=1
            ),
        ]
    )

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        if experiment_id == SLOW_EXPERIMENT:
            try:
                await asyncio.wait_for(fast_published.wait(), timeout=15)
            except TimeoutError:
                raise ApplicationError("the fast experiment never published", non_retryable=True)
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        publish_calls.append(experiment_id)
        if experiment_id == FAST_EXPERIMENT:
            fast_published.set()
        return f"recalc-{experiment_id}"

    with patch("temporalio.workflow.metric_meter") as mock_meter:
        result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert publish_calls == [FAST_EXPERIMENT, SLOW_EXPERIMENT]
    assert result == {"hour": 2, "total": 2, "succeeded": 2, "failed": 0, "recalculations_synced": 2}
    # Asserted through the harness so the test fails if the workflow body stops calling the helper,
    # which would silently kill the missing-publish alert.
    mock_meter.return_value.with_additional_attributes.assert_called_once_with(
        {"workflow_type": "experiment-saved-metrics-workflow", "status": "published"}
    )


@pytest.mark.asyncio
async def test_publish_does_not_wait_in_the_metric_semaphore_queue():
    """Every metric task in the hour enqueues on the shared metric semaphore up front, and waiters are
    served in order. A publish that waited in that queue would sit behind the whole remaining batch. Here
    the batch saturates the ten metric slots and every slow metric only completes after the fast
    experiment's publish, so a queued-behind-metrics publish deadlocks and fails via the timeout guard."""
    fast_published = asyncio.Event()

    slow = [
        ExperimentSavedMetricInput(
            experiment_id=SLOW_EXPERIMENT, metric_uuid=f"m-slow-{i}", fingerprint=f"s{i}", team_id=1
        )
        for i in range(14)
    ]
    mock_discover = _single_page(
        [
            ExperimentSavedMetricInput(
                experiment_id=FAST_EXPERIMENT, metric_uuid="m-fast", fingerprint="f1", team_id=1
            ),
            *slow,
        ]
    )

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        if experiment_id == SLOW_EXPERIMENT:
            try:
                await asyncio.wait_for(fast_published.wait(), timeout=15)
            except TimeoutError:
                raise ApplicationError("the fast experiment never published", non_retryable=True)
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        if experiment_id == FAST_EXPERIMENT:
            fast_published.set()
        return f"recalc-{experiment_id}"

    result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert result == {"hour": 2, "total": 15, "succeeded": 15, "failed": 0, "recalculations_synced": 2}


@pytest.mark.asyncio
async def test_a_failed_publish_skips_only_its_own_experiment():
    """One experiment's publish failing after its retries must not fail the workflow or block the other
    experiments' publishes, or a single bad row would lose the whole hour's freshness."""

    mock_discover = _single_page(
        [
            ExperimentSavedMetricInput(
                experiment_id=FAST_EXPERIMENT, metric_uuid="m-fast", fingerprint="f1", team_id=1
            ),
            ExperimentSavedMetricInput(
                experiment_id=SLOW_EXPERIMENT, metric_uuid="m-slow", fingerprint="f2", team_id=1
            ),
        ]
    )

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        if experiment_id == FAST_EXPERIMENT:
            raise ApplicationError("publish rejected", non_retryable=True)
        return f"recalc-{experiment_id}"

    result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert result == {"hour": 2, "total": 2, "succeeded": 2, "failed": 0, "recalculations_synced": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("force_continue_as_new", [False, True])
async def test_the_run_covers_every_page_and_carries_state_across_legs(force_continue_as_new):
    """The hour used to run as one execution and Temporal Cloud terminated it at the history cap, so
    experiments past the cutoff were silently skipped. The run must cover every discovery page: within
    one execution, and equally when forced to continue-as-new on every page boundary, where a dropped
    cursor skips a page, a re-stamped run_started_at breaks the publish window, dropped totals corrupt
    the summary, and a per-leg counter emission double-counts the run. The middle page is empty with a
    cursor still set, which is what a page of all-filtered-out experiments returns: a run that stops on
    the empty metrics list instead of the cursor silently drops the rest of the batch."""
    pages = {
        0: SavedMetricsPage(
            metrics=[
                ExperimentSavedMetricInput(
                    experiment_id=FAST_EXPERIMENT, metric_uuid="m-1", fingerprint="f1", team_id=1
                )
            ],
            next_after_experiment_id=FAST_EXPERIMENT,
        ),
        FAST_EXPERIMENT: SavedMetricsPage(metrics=[], next_after_experiment_id=150),
        150: SavedMetricsPage(
            metrics=[
                ExperimentSavedMetricInput(experiment_id=202, metric_uuid="m-2", fingerprint="f2", team_id=1),
                ExperimentSavedMetricInput(experiment_id=202, metric_uuid="m-3", fingerprint="f3", team_id=1),
            ],
            next_after_experiment_id=None,
        ),
    }
    publish_run_starts: dict[int, str] = {}

    @activity.defn(name="get_experiment_saved_metrics_page")
    async def mock_discover(inputs: MetricsPageInput) -> SavedMetricsPage:
        return pages[inputs.after_experiment_id]

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        publish_run_starts[experiment_id] = run_started_at
        return f"recalc-{experiment_id}"

    force_threshold = 0 if force_continue_as_new else 20_000
    with (
        patch("posthog.temporal.experiments.workflows.FORCE_CONTINUE_HISTORY_EVENTS", force_threshold),
        patch("temporalio.workflow.metric_meter") as mock_meter,
    ):
        result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert result == {"hour": 2, "total": 3, "succeeded": 3, "failed": 0, "recalculations_synced": 2}
    assert set(publish_run_starts) == {FAST_EXPERIMENT, 202}
    # Both publishes must receive the first leg's run start; the sync activity windows qualifying
    # points on it and the regular and saved workflows share recalculation rows through it.
    assert len(set(publish_run_starts.values())) == 1
    mock_meter.return_value.with_additional_attributes.assert_called_once_with(
        {"workflow_type": "experiment-saved-metrics-workflow", "status": "published"}
    )


@pytest.mark.parametrize(
    "succeeded,recalculations_synced,expected_status",
    [(2, 2, "published"), (2, 0, "missing"), (0, 0, None)],
)
def test_publish_outcome_counter_feeds_the_missing_publish_alert(
    succeeded: int, recalculations_synced: int, expected_status: str | None
) -> None:
    """The "missing" emission is the alert signal for runs that compute results users never see. A flipped
    condition kills the alert; emitting on runs that computed nothing floods it with false positives."""
    with (
        patch("temporalio.workflow.metric_meter") as mock_meter,
        patch("temporalio.workflow.info") as mock_info,
    ):
        mock_info.return_value.workflow_type = "experiment-saved-metrics-workflow"
        _record_publish_outcome(succeeded, recalculations_synced)

    if expected_status is None:
        mock_meter.assert_not_called()
        return
    with_attributes = mock_meter.return_value.with_additional_attributes
    with_attributes.assert_called_once_with(
        {"workflow_type": "experiment-saved-metrics-workflow", "status": expected_status}
    )
    with_attributes.return_value.create_counter.return_value.add.assert_called_once_with(1)
