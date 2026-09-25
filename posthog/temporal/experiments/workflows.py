import asyncio
from datetime import datetime, timedelta

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
        ExperimentRegularMetricsWorkflowInputs,
        ExperimentSavedMetricsWorkflowInputs,
        ExperimentTimeseriesRecalculationWorkflowInputs,
    )

MAX_CONCURRENT_METRICS = 10


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


@temporalio.workflow.defn(name="experiment-regular-metrics-workflow")
class ExperimentRegularMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-metrics for teams scheduled at this hour
    2. Per experiment: calculates its metrics in parallel (one activity per metric, shared concurrency
       limit), then assembles its completed metrics recalculation from this run's points
    3. Returns summary of successes/failures
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentRegularMetricsWorkflowInputs:
        return ExperimentRegularMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentRegularMetricsWorkflowInputs) -> dict:
        run_started_at = temporalio.workflow.now()

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
                "recalculations_synced": 0,
            }

        # Step 2: Per experiment, calculate its metrics and publish its recalculation as soon as they
        # finish, so a team's results land minutes after its own experiments compute instead of hours
        # after the whole batch. The patch gates keep replay of older histories deterministic.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

        if temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, recalculations_synced = await _calculate_and_publish_per_experiment(
                calculate_experiment_regular_metric, experiment_metrics, run_started_at, semaphore
            )
        else:

            async def _run_metric(em):
                async with semaphore:
                    return await temporalio.workflow.execute_activity(
                        calculate_experiment_regular_metric,
                        args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=RetryPolicy(
                            maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(seconds=60),
                        ),
                    )

            tasks = [_run_metric(em) for em in experiment_metrics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            recalculations_synced = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                recalculations_synced = await _create_recalculations_from_timeseries(
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

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
            "recalculations_synced": recalculations_synced,
        }


@temporalio.workflow.defn(name="experiment-saved-metrics-workflow")
class ExperimentSavedMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment saved metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-saved metrics for teams scheduled at this hour
    2. Per experiment: calculates its metrics in parallel (one activity per metric, shared concurrency
       limit), then assembles its completed metrics recalculation from this run's points
    3. Returns summary of successes/failures
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentSavedMetricsWorkflowInputs:
        return ExperimentSavedMetricsWorkflowInputs(hour=int(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentSavedMetricsWorkflowInputs) -> dict:
        run_started_at = temporalio.workflow.now()

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
                "recalculations_synced": 0,
            }

        # Step 2: Per experiment, calculate its metrics and publish its recalculation as soon as they
        # finish, so a team's results land minutes after its own experiments compute instead of hours
        # after the whole batch. The patch gates keep replay of older histories deterministic.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

        if temporalio.workflow.patched("experiment-per-experiment-publish-2026-09"):
            results, recalculations_synced = await _calculate_and_publish_per_experiment(
                calculate_experiment_saved_metric, experiment_metrics, run_started_at, semaphore
            )
        else:

            async def _run_metric(em):
                async with semaphore:
                    return await temporalio.workflow.execute_activity(
                        calculate_experiment_saved_metric,
                        args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=RetryPolicy(
                            maximum_attempts=TIMESERIES_METRIC_MAX_ATTEMPTS,
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(seconds=60),
                        ),
                    )

            tasks = [_run_metric(em) for em in experiment_metrics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            recalculations_synced = 0
            if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
                recalculations_synced = await _create_recalculations_from_timeseries(
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

        return {
            "hour": inputs.hour,
            "total": len(experiment_metrics),
            "succeeded": succeeded,
            "failed": failed,
            "recalculations_synced": recalculations_synced,
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
