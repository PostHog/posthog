import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.experiments.activities import (
        backfill_experiment_metric,
        calculate_experiment_regular_metric,
        calculate_experiment_saved_metric,
        create_recalculation_from_timeseries,
        get_experiment_regular_metrics_for_hour,
        get_experiment_saved_metrics_for_hour,
    )
    from posthog.temporal.experiments.models import (
        TIMESERIES_METRIC_MAX_ATTEMPTS,
        ExperimentRegularMetricInput,
        ExperimentRegularMetricResult,
        ExperimentRegularMetricsWorkflowInputs,
        ExperimentSavedMetricInput,
        ExperimentSavedMetricResult,
        ExperimentSavedMetricsWorkflowInputs,
        ExperimentTimeseriesRecalculationWorkflowInputs,
    )

MAX_CONCURRENT_METRICS = 10

# One helper serves both workflows, so its metric type is whichever pair the caller passes.
type MetricInput = ExperimentRegularMetricInput | ExperimentSavedMetricInput
type MetricResult = ExperimentRegularMetricResult | ExperimentSavedMetricResult


def _record_publish_outcome(succeeded: int, recalculations_synced: int) -> None:
    """Per-run publish counter for the executions that still publish.

    A run that computed metrics but published zero recalculation rows is the silent-failure mode
    where results exist yet never reach users. Only the legacy branches call this, so the counter
    keeps that meaning: on the calculate-only path nothing publishes by design, and emitting there
    would report every healthy run as missing.

    `workflow.metric_meter()` skips emission during replay, so no patch gate is needed.
    """
    if succeeded == 0:
        return
    status = "published" if recalculations_synced > 0 else "missing"
    try:
        temporalio.workflow.metric_meter().with_additional_attributes(
            {"workflow_type": temporalio.workflow.info().workflow_type, "status": status}
        ).create_counter(
            "experiment_timeseries_publish_runs",
            "Hourly experiment timeseries runs that computed metrics, by whether they published recalculation rows.",
        ).add(1)
    except Exception:
        # A meter failure must not fail a run whose calculations and publishes already finished.
        temporalio.workflow.logger.warning("Failed to record the publish outcome counter", exc_info=True)


async def _create_recalculations_from_timeseries(
    experiments: set[tuple[int, int]], run_started_at: datetime, semaphore: asyncio.Semaphore
) -> int:
    """One activity per (experiment, team) this run touched; returns how many recalculation rows gained copies.

    Pre-patch publish pass, kept only so executions recorded before the per-experiment publish replay
    deterministically."""

    async def _sync_experiment(experiment_id: int, team_id: int) -> str | None:
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                create_recalculation_from_timeseries,
                args=[experiment_id, team_id, run_started_at.isoformat()],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

    results = await asyncio.gather(
        *[_sync_experiment(experiment_id, team_id) for experiment_id, team_id in sorted(experiments)],
        return_exceptions=True,
    )
    return sum(1 for result in results if isinstance(result, str))


async def _calculate_and_publish_per_experiment(
    calculate_activity,
    experiment_metrics,
    run_started_at: datetime,
    semaphore: asyncio.Semaphore,
) -> tuple[list, int]:
    """Calculate each experiment's metrics and publish its recalculation as soon as its own metrics finish.

    Grouped per experiment so a slow experiment, or a worker restart mid-hour, delays only its own publish
    instead of every experiment in the batch. Metric activities share the caller's semaphore, so query
    concurrency is the same as one flat fan-out. Returns the per-metric results and the publish count.
    """

    async def _run_metric(em):
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                calculate_activity,
                args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                ),
            )

    groups: dict[tuple[int, int | None], list] = {}
    for em in experiment_metrics:
        groups.setdefault((em.experiment_id, em.team_id), []).append(em)

    # Publishes get their own limit. Every metric task in the hour enqueues on the shared semaphore up
    # front and waiters are served in order, so a publish waiting in that queue would sit behind the whole
    # remaining batch, which recreates the end-of-hour barrier this function exists to remove.
    publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

    async def _run_experiment(experiment_id: int, team_id: int | None, metrics: list) -> tuple[list, bool]:
        metric_results = await asyncio.gather(*[_run_metric(em) for em in metrics], return_exceptions=True)
        if team_id is None:
            return metric_results, False
        try:
            async with publish_semaphore:
                synced = await temporalio.workflow.execute_activity(
                    create_recalculation_from_timeseries,
                    args=[experiment_id, team_id, run_started_at.isoformat()],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
        except ActivityError:
            # A failed publish loses one experiment's freshness until the next run; it must not fail
            # the rest of the hour's calculations.
            return metric_results, False
        return metric_results, isinstance(synced, str)

    group_results = await asyncio.gather(
        *[_run_experiment(experiment_id, team_id, metrics) for (experiment_id, team_id), metrics in groups.items()]
    )
    results = [result for metric_results, _ in group_results for result in metric_results]
    published = sum(1 for _, synced in group_results if synced)
    return results, published


async def _calculate_metrics(
    calculate_activity: Callable[..., Any],
    experiment_metrics: Sequence[MetricInput],
    semaphore: asyncio.Semaphore,
) -> list[MetricResult | BaseException]:
    """Run one activity per metric, bounded by the shared concurrency limit."""

    async def _run_metric(em: MetricInput) -> MetricResult:
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                calculate_activity,
                args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                ),
            )

    return await asyncio.gather(*[_run_metric(em) for em in experiment_metrics], return_exceptions=True)


@temporalio.workflow.defn(name="experiment-regular-metrics-workflow")
class ExperimentRegularMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-metrics for teams scheduled at this hour
    2. Calculates those metrics in parallel (one activity per metric, shared concurrency limit)
    3. Returns summary of successes/failures
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentRegularMetricsWorkflowInputs:
        return ExperimentRegularMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentRegularMetricsWorkflowInputs) -> dict:
        # Step 1: Discover experiment-metrics for this hour
        experiment_metrics = await temporalio.workflow.execute_activity(
            get_experiment_regular_metrics_for_hour,
            inputs.hour,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not experiment_metrics:
            return {
                "hour": inputs.hour,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
            }

        # Step 2: Calculate every metric, bounded by one shared concurrency limit.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)
        run_started_at = temporalio.workflow.now()

        # Only an execution carrying this marker skips the publish activities. A history without it
        # replays the commands it recorded, so the branches below must stay until no such execution
        # is left. These workflows set no execution timeout, so nothing bounds that wait.
        published: int | None = None
        if temporalio.workflow.patched("experiment-drop-timeseries-publish-2026-10"):
            results = await _calculate_metrics(calculate_experiment_regular_metric, experiment_metrics, semaphore)
        elif temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, published = await _calculate_and_publish_per_experiment(
                calculate_experiment_regular_metric, experiment_metrics, run_started_at, semaphore
            )
        else:
            results = await _calculate_metrics(calculate_experiment_regular_metric, experiment_metrics, semaphore)
            published = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                published = await _create_recalculations_from_timeseries(
                    {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                    run_started_at,
                    semaphore,
                )

        # Step 3: Summarize
        succeeded = 0
        failed = 0

        for result in results:
            if isinstance(result, BaseException):
                failed += 1
            elif result.success:
                succeeded += 1
            else:
                failed += 1

        if published is not None:
            _record_publish_outcome(succeeded, published)

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
        }


@temporalio.workflow.defn(name="experiment-saved-metrics-workflow")
class ExperimentSavedMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment saved metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-saved metrics for teams scheduled at this hour
    2. Calculates those metrics in parallel (one activity per metric, shared concurrency limit)
    3. Returns summary of successes/failures
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentSavedMetricsWorkflowInputs:
        return ExperimentSavedMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentSavedMetricsWorkflowInputs) -> dict:
        # Step 1: Discover experiment-saved metrics for this hour
        experiment_metrics = await temporalio.workflow.execute_activity(
            get_experiment_saved_metrics_for_hour,
            inputs.hour,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not experiment_metrics:
            return {
                "hour": inputs.hour,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
            }

        # Step 2: Calculate every metric, bounded by one shared concurrency limit.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)
        run_started_at = temporalio.workflow.now()

        # Only an execution carrying this marker skips the publish activities. A history without it
        # replays the commands it recorded, so the branches below must stay until no such execution
        # is left. These workflows set no execution timeout, so nothing bounds that wait.
        published: int | None = None
        if temporalio.workflow.patched("experiment-drop-timeseries-publish-2026-10"):
            results = await _calculate_metrics(calculate_experiment_saved_metric, experiment_metrics, semaphore)
        elif temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, published = await _calculate_and_publish_per_experiment(
                calculate_experiment_saved_metric, experiment_metrics, run_started_at, semaphore
            )
        else:
            results = await _calculate_metrics(calculate_experiment_saved_metric, experiment_metrics, semaphore)
            published = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                published = await _create_recalculations_from_timeseries(
                    {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                    run_started_at,
                    semaphore,
                )

        # Step 3: Summarize
        succeeded = 0
        failed = 0

        for result in results:
            if isinstance(result, BaseException):
                failed += 1
            elif result.success:
                succeeded += 1
            else:
                failed += 1

        if published is not None:
            _record_publish_outcome(succeeded, published)

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
        }


@temporalio.workflow.defn(name="experiment-timeseries-recalculation-workflow")
class ExperimentTimeseriesRecalculationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentTimeseriesRecalculationWorkflowInputs:
        return ExperimentTimeseriesRecalculationWorkflowInputs(recalculation_id=inputs[0])

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentTimeseriesRecalculationWorkflowInputs) -> dict:
        return await temporalio.workflow.execute_activity(
            backfill_experiment_metric,
            inputs.recalculation_id,
            start_to_close_timeout=timedelta(hours=3),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=5)),
            heartbeat_timeout=timedelta(minutes=20),
        )
