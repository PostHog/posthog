"""Activities for workflow failure alerting."""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import requests
import structlog
from temporalio import activity

from posthog.temporal.common.client import async_connect

logger = structlog.get_logger(__name__)


@dataclass
class CountFailedWorkflowsInputs:
    """Inputs for counting failed workflows."""

    lookback_minutes: int = 60


@dataclass
class CountFailedWorkflowsOutput:
    """Output from counting failed workflows."""

    failed_count: int
    failed_workflows: list[dict[str, Any]]
    time_range_start: str
    time_range_end: str


@activity.defn
async def count_failed_workflows_activity(inputs: CountFailedWorkflowsInputs) -> CountFailedWorkflowsOutput:
    """Count the number of failed workflows in the given time range.

    Uses Temporal's list_workflows API to query for failed workflow executions.
    """
    now = dt.datetime.now(tz=dt.UTC)
    time_range_start = now - dt.timedelta(minutes=inputs.lookback_minutes)

    # Format times for Temporal query
    start_str = time_range_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Query for failed workflows in the time range
    # Using Temporal's visibility query language
    query = f"ExecutionStatus = 'Failed' AND CloseTime >= '{start_str}' AND CloseTime <= '{end_str}'"

    client = await async_connect()

    failed_workflows: list[dict[str, Any]] = []
    async for workflow in client.list_workflows(query=query):
        workflow_info = {
            "workflow_id": workflow.id,
            "workflow_type": workflow.workflow_type,
            "run_id": workflow.run_id,
            "status": workflow.status.name if workflow.status else "UNKNOWN",
            "close_time": workflow.close_time.isoformat() if workflow.close_time else None,
            "execution_time": workflow.execution_time.isoformat() if workflow.execution_time else None,
        }
        failed_workflows.append(workflow_info)

    logger.info(
        "Counted failed workflows",
        failed_count=len(failed_workflows),
        time_range_start=start_str,
        time_range_end=end_str,
    )

    return CountFailedWorkflowsOutput(
        failed_count=len(failed_workflows),
        failed_workflows=failed_workflows,
        time_range_start=start_str,
        time_range_end=end_str,
    )


@dataclass
class SendSlackAlertInputs:
    """Inputs for sending Slack alert."""

    failed_count: int
    failed_workflows: list[dict[str, Any]]
    time_range_start: str
    time_range_end: str
    previous_failed_count: int = 0


@activity.defn
async def send_slack_alert_activity(inputs: SendSlackAlertInputs) -> bool:
    """Send a Slack alert about workflow failures.

    Returns True if alert was sent successfully, False otherwise.
    """
    webhook_url = settings.TEMPORAL_WORKFLOW_FAILURE_SLACK_WEBHOOK_URL

    if not webhook_url:
        logger.warning("Slack webhook URL not configured, skipping alert")
        return False

    if not settings.CLOUD_DEPLOYMENT:
        logger.info("Skipping Slack alert in non-cloud environment")
        return False

    # Build Slack message blocks
    environment = (
        f"{settings.CLOUD_DEPLOYMENT} :flag-{settings.CLOUD_DEPLOYMENT}:" if settings.CLOUD_DEPLOYMENT else "unknown"
    )

    # Build summary of failed workflows by type
    workflow_type_counts: dict[str, int] = {}
    for workflow in inputs.failed_workflows:
        wf_type = workflow.get("workflow_type", "unknown")
        workflow_type_counts[wf_type] = workflow_type_counts.get(wf_type, 0) + 1

    workflow_summary = "\n".join([f"• `{wf_type}`: {count}" for wf_type, count in sorted(workflow_type_counts.items())])

    # Build sample of recent failures (limit to 5 for readability)
    recent_failures = inputs.failed_workflows[:5]
    failure_details = "\n".join(
        [f"• `{wf['workflow_id']}` ({wf.get('workflow_type', 'unknown')})" for wf in recent_failures]
    )
    if len(inputs.failed_workflows) > 5:
        failure_details += f"\n... and {len(inputs.failed_workflows) - 5} more"

    # Determine alert severity
    increase = inputs.failed_count - inputs.previous_failed_count
    if increase > 10:
        severity_emoji = ":rotating_light:"
        severity_text = "High"
    elif increase > 5:
        severity_emoji = ":warning:"
        severity_text = "Medium"
    else:
        severity_emoji = ":information_source:"
        severity_text = "Low"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{severity_emoji} Temporal Workflow Failures Detected",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Failed Workflows:*\n{inputs.failed_count}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity_text}"},
                {"type": "mrkdwn", "text": f"*Time Range:*\n{inputs.time_range_start} to {inputs.time_range_end}"},
                {"type": "mrkdwn", "text": f"*Change:*\n+{increase} from previous check"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Failures by Workflow Type:*\n{workflow_summary}"
                if workflow_summary
                else "*No failures by type*",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Recent Failed Workflows:*\n{failure_details}" if failure_details else "*No recent failures*",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":globe_with_meridians: *Environment:* {environment} | :clock1: *Alert Time:* {dt.datetime.now(tz=dt.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                },
            ],
        },
    ]

    # Add link to Temporal UI if namespace is known
    namespace = settings.TEMPORAL_NAMESPACE
    if namespace and namespace != "default":
        temporal_url = (
            f"https://cloud.temporal.io/namespaces/{namespace}/workflows?query=ExecutionStatus%3D%27Failed%27"
        )
        blocks.insert(
            -1,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":link: <{temporal_url}|View Failed Workflows in Temporal UI>",
                },
            },
        )

    payload = {"blocks": blocks}

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Slack alert sent successfully", failed_count=inputs.failed_count)
        return True
    except requests.RequestException as e:
        logger.warning("Failed to send Slack alert", error=str(e))
        return False
