"""Temporal workflows for ingestion limits monitoring."""

from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.ingestion_limits.activities import (
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
)
from posthog.temporal.ingestion_limits.types import IngestionLimitsWorkflowInput, ReportIngestionLimitsInput


@workflow.defn(name="ingestion-limits-report")
class IngestionLimitsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> IngestionLimitsWorkflowInput:
        """Parse inputs from the management command CLI."""
        parsed_input = (
            IngestionLimitsWorkflowInput.model_validate_json(inputs[0])
            if inputs
            else IngestionLimitsWorkflowInput(event_threshold=1000)
        )
        return parsed_input

    @workflow.run
    async def run(self, input: IngestionLimitsWorkflowInput) -> None:
        report = await workflow.execute_activity(
            query_ingestion_limits_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )

        await workflow.execute_activity(
            report_ingestion_limits_activity,
            ReportIngestionLimitsInput(workflow_inputs=input, report=report),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )
