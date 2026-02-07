import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.experiments.activities import (
        calculate_experiment_regular_metric,
        calculate_experiment_saved_metric,
        get_experiment_regular_metrics_for_hour,
        get_experiment_saved_metrics_for_hour,
    )
    from posthog.temporal.experiments.models import (
        ExperimentRegularMetricsWorkflowInputs,
        ExperimentSavedMetricsWorkflowInputs,
    )


@temporalio.workflow.defn(name="experiment-regular-metrics-workflow")
class ExperimentRegularMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-metrics for teams scheduled at this hour
    2. Calculates each metric in parallel (one activity per metric)
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

        # Step 2: Calculate each metric in parallel
        tasks = [
            temporalio.workflow.execute_activity(
                calculate_experiment_regular_metric,
                args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            for em in experiment_metrics
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

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
        }


@temporalio.workflow.defn(name="experiment-saved-metrics-workflow")
class ExperimentSavedMetricsWorkflow(PostHogWorkflow):
    """
    Workflow that calculates all experiment saved metrics for teams scheduled at a given hour.

    Runs daily per hour (24 schedules total). Each run:
    1. Discovers experiment-saved metrics for teams scheduled at this hour
    2. Calculates each metric in parallel (one activity per metric)
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

        # Step 2: Calculate each metric in parallel
        tasks = [
            temporalio.workflow.execute_activity(
                calculate_experiment_saved_metric,
                args=[em.experiment_id, em.metric_uuid, em.fingerprint],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            for em in experiment_metrics
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

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
        }
