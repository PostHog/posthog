import asyncio
from datetime import datetime, timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

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
    """One activity per (experiment, team) this run touched; returns how many recalculation rows gained copies."""

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


@temporalio.workflow.defn(name="experiment-regular-metrics-workflow")
class ExperimentRegularMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-metrics for teams scheduled at this hour
    2. Calculates each metric in parallel (one activity per metric)
    3. Assembles a completed metrics recalculation per experiment from this run's points
    4. Returns summary of successes/failures
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

        # Step 2: Calculate each metric with limited concurrency
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

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

        # Step 3: Assemble a recalculation per experiment from the points this run wrote, so the latest read
        # serves them without a recompute. Points are matched against the run start, so the stamp is taken
        # before discovery. The patch gate keeps replay of histories recorded without this step deterministic.
        recalculations_synced = 0
        if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
            recalculations_synced = await _create_recalculations_from_timeseries(
                {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                run_started_at,
                semaphore,
            )

        # Step 4: Summarize
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
    2. Calculates each metric in parallel (one activity per metric)
    3. Assembles a completed metrics recalculation per experiment from this run's points
    4. Returns summary of successes/failures
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

        # Step 2: Calculate each metric with limited concurrency
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

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

        # Step 3: Assemble a recalculation per experiment from the points this run wrote, so the latest read
        # serves them without a recompute. Points are matched against the run start, so the stamp is taken
        # before discovery. The patch gate keeps replay of histories recorded without this step deterministic.
        recalculations_synced = 0
        if temporalio.workflow.patched("experiment-timeseries-recalculation-sync-2026-09"):
            recalculations_synced = await _create_recalculations_from_timeseries(
                {(em.experiment_id, em.team_id) for em in experiment_metrics if em.team_id is not None},
                run_started_at,
                semaphore,
            )

        # Step 4: Summarize
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
