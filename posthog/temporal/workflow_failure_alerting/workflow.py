"""Workflow for monitoring and alerting on Temporal workflow failures."""

import json
import datetime as dt
from dataclasses import dataclass

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.workflow_failure_alerting.activities import (
    CountFailedWorkflowsInputs,
    SendSlackAlertInputs,
    count_failed_workflows_activity,
    send_slack_alert_activity,
)

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "workflow-failure-alerting"
SCHEDULE_ID = "workflow-failure-alerting-schedule"

# Thresholds for alerting
DEFAULT_LOOKBACK_MINUTES = 60
DEFAULT_FAILURE_THRESHOLD = 1  # Alert when at least this many failures


@dataclass
class WorkflowFailureAlertingInputs:
    """Inputs for the workflow failure alerting workflow."""

    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    previous_failed_count: int = 0


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class WorkflowFailureAlertingWorkflow(PostHogWorkflow):
    """Workflow that monitors for failed Temporal workflows and sends alerts to Slack.

    This workflow:
    1. Queries Temporal for failed workflows in the lookback period
    2. If failures exceed the threshold, sends an alert to Slack
    3. Returns the count of failed workflows for the next run to compare

    The workflow is designed to run on a schedule (e.g., every 15 minutes).
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> WorkflowFailureAlertingInputs:
        """Parse workflow inputs from string list or JSON."""
        if not inputs:
            return WorkflowFailureAlertingInputs()

        try:
            # Try to parse as JSON first
            parsed = json.loads(inputs[0])
            return WorkflowFailureAlertingInputs(**parsed)
        except (json.JSONDecodeError, TypeError):
            # Fall back to positional arguments
            return WorkflowFailureAlertingInputs(
                lookback_minutes=int(inputs[0]) if len(inputs) > 0 else DEFAULT_LOOKBACK_MINUTES,
                failure_threshold=int(inputs[1]) if len(inputs) > 1 else DEFAULT_FAILURE_THRESHOLD,
                previous_failed_count=int(inputs[2]) if len(inputs) > 2 else 0,
            )

    @temporalio.workflow.run
    async def run(self, inputs: WorkflowFailureAlertingInputs) -> dict:
        """Execute the workflow failure alerting workflow."""
        logger.info(
            "Starting workflow failure alerting",
            lookback_minutes=inputs.lookback_minutes,
            failure_threshold=inputs.failure_threshold,
            previous_failed_count=inputs.previous_failed_count,
        )

        # Count failed workflows
        count_result = await temporalio.workflow.execute_activity(
            count_failed_workflows_activity,
            CountFailedWorkflowsInputs(lookback_minutes=inputs.lookback_minutes),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_attempts=3,
            ),
        )

        logger.info(
            "Counted failed workflows",
            failed_count=count_result.failed_count,
            previous_count=inputs.previous_failed_count,
        )

        # Check if we should send an alert
        should_alert = (
            count_result.failed_count >= inputs.failure_threshold
            and count_result.failed_count > inputs.previous_failed_count
        )

        alert_sent = False
        if should_alert:
            logger.info(
                "Sending alert for workflow failures",
                failed_count=count_result.failed_count,
                threshold=inputs.failure_threshold,
            )

            alert_sent = await temporalio.workflow.execute_activity(
                send_slack_alert_activity,
                SendSlackAlertInputs(
                    failed_count=count_result.failed_count,
                    failed_workflows=count_result.failed_workflows,
                    time_range_start=count_result.time_range_start,
                    time_range_end=count_result.time_range_end,
                    previous_failed_count=inputs.previous_failed_count,
                ),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_attempts=3,
                ),
            )
        else:
            logger.info(
                "No alert needed",
                failed_count=count_result.failed_count,
                threshold=inputs.failure_threshold,
                previous_count=inputs.previous_failed_count,
            )

        return {
            "failed_count": count_result.failed_count,
            "alert_sent": alert_sent,
            "time_range_start": count_result.time_range_start,
            "time_range_end": count_result.time_range_end,
        }
