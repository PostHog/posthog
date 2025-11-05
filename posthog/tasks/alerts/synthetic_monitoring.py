"""
Celery tasks for synthetic monitoring alerting and check scheduling.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

import boto3
import requests
import structlog
from botocore.config import Config
from celery import shared_task

from posthog.api.capture import capture_internal
from posthog.email import EmailMessage
from posthog.event_usage import report_team_action
from posthog.models import SyntheticMonitor
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Lambda configuration
LAMBDA_FUNCTION_NAME = getattr(settings, "SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME", "posthog-synthetic-monitor")
LAMBDA_TIMEOUT = 15  # seconds to wait for Lambda response


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=3,
)
def schedule_synthetic_checks() -> None:
    """
    Scheduled task to trigger synthetic monitoring checks that are due.
    Runs every minute to check for monitors that need to be executed.
    """
    now = datetime.now(UTC)

    # Find monitors that are enabled and due for a check
    due_monitors = SyntheticMonitor.objects.filter(enabled=True, next_check_at__lte=now).select_related("team")

    if not due_monitors.exists():
        return

    logger.info("Scheduling synthetic checks", count=due_monitors.count())

    for monitor in due_monitors:
        # If monitor has specific regions configured, run check in each region
        regions = monitor.regions if monitor.regions else ["us-east-1"]

        for region in regions:
            try:
                execute_http_check.delay(monitor_id=str(monitor.id), region=region)
            except Exception as e:
                logger.exception(
                    "Failed to trigger check",
                    monitor_id=str(monitor.id),
                    region=region,
                    error=str(e),
                )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=3,
)
def execute_http_check(monitor_id: str, region: str = "us-east-1") -> None:
    """
    Execute an HTTP check for a synthetic monitor by invoking AWS Lambda.
    Waits for the Lambda response with a 15-second timeout.
    """
    try:
        monitor = SyntheticMonitor.objects.select_related("team").get(id=monitor_id)
    except SyntheticMonitor.DoesNotExist:
        logger.exception("Monitor not found", monitor_id=monitor_id)
        return

    # Prepare Lambda payload
    payload = {
        "url": monitor.url,
        "method": monitor.method,
        "headers": monitor.headers or {},
        "body": monitor.body,
        "expected_status_code": monitor.expected_status_code,
        "timeout_seconds": monitor.timeout_seconds,
        "monitor_id": str(monitor.id),
        "monitor_name": monitor.name,
    }

    # Invoke Lambda function
    success = False
    status_code = None
    error_message = None
    response_time_ms = None

    try:
        # Create Lambda client for the specified region
        lambda_config = Config(
            region_name=region,
            read_timeout=LAMBDA_TIMEOUT,
            connect_timeout=5,
        )
        lambda_client = boto3.client("lambda", config=lambda_config)

        # Invoke Lambda function synchronously
        start_time = time.time()
        lambda_response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",  # Synchronous invocation
            Payload=json.dumps(payload),
        )
        invocation_time_ms = int((time.time() - start_time) * 1000)

        # Parse Lambda response
        response_payload = json.loads(lambda_response["Payload"].read())

        # Extract check results from Lambda response
        success = response_payload.get("success", False)
        status_code = response_payload.get("status_code")
        response_time_ms = response_payload.get("response_time_ms", 0)
        error_message = response_payload.get("error_message")

        logger.info(
            "HTTP check completed via Lambda",
            monitor_id=str(monitor.id),
            url=monitor.url,
            region=region,
            success=success,
            status_code=status_code,
            response_time_ms=response_time_ms,
            lambda_invocation_ms=invocation_time_ms,
        )

    except lambda_client.exceptions.ResourceNotFoundException:
        error_message = f"Lambda function '{LAMBDA_FUNCTION_NAME}' not found in region '{region}'"
        response_time_ms = 0
        logger.exception("Lambda function not found", monitor_id=str(monitor.id), region=region)

    except lambda_client.exceptions.TooManyRequestsException:
        error_message = f"Lambda throttled in region '{region}'"
        response_time_ms = 0
        logger.warning("Lambda throttled", monitor_id=str(monitor.id), region=region)

    except Exception as e:
        error_message = f"Lambda invocation failed: {str(e)}"
        response_time_ms = 0
        logger.exception("Lambda invocation error", monitor_id=str(monitor.id), region=region, error=str(e))

    # Update monitor state
    if success:
        monitor.record_success()
    else:
        monitor.record_failure()

    monitor.save(update_fields=["state", "last_checked_at", "next_check_at", "consecutive_failures"])

    # Emit event to PostHog
    try:
        capture_internal(
            distinct_id=f"monitor_{monitor.id}",
            team_id=monitor.team_id,
            event="synthetic_http_check",
            properties={
                "monitor_id": str(monitor.id),
                "monitor_name": monitor.name,
                "url": monitor.url,
                "method": monitor.method,
                "region": region,
                "success": success,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "error_message": error_message,
                "expected_status_code": monitor.expected_status_code,
                "consecutive_failures": monitor.consecutive_failures,
            },
        )
    except Exception as e:
        logger.exception("Failed to emit synthetic check event", monitor_id=str(monitor.id), error=str(e))

    # Trigger alert if needed
    if monitor.should_trigger_alert():
        send_synthetic_monitor_alert.delay(
            monitor_id=str(monitor.id),
            error_message=error_message or "Check failed",
            status_code=status_code,
            response_time_ms=response_time_ms,
            region=region,
        )

    logger.info("HTTP check processed", monitor_id=str(monitor.id), success=success)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=3,
)
def send_synthetic_monitor_alert(
    monitor_id: str, error_message: str, status_code: int | None, response_time_ms: int | None, region: str
) -> None:
    """
    Send alert notifications when a synthetic monitor fails.
    Supports email and Slack notifications.
    """
    try:
        monitor = (
            SyntheticMonitor.objects.select_related("team", "slack_integration")
            .prefetch_related("alert_recipients")
            .get(id=monitor_id)
        )
    except SyntheticMonitor.DoesNotExist:
        logger.exception("Monitor not found", monitor_id=monitor_id)
        return

    # Check if we should send alert (respect cooldown period)
    if monitor.last_alerted_at:
        # Don't send alerts more frequently than once per hour
        hours_since_last_alert = (datetime.now(UTC) - monitor.last_alerted_at).total_seconds() / 3600
        if hours_since_last_alert < 1:
            logger.info(
                "Skipping alert due to cooldown",
                monitor_id=str(monitor.id),
                hours_since_last_alert=hours_since_last_alert,
            )
            return

    # Prepare alert data
    alert_context = {
        "monitor_name": monitor.name,
        "monitor_url": monitor.url,
        "consecutive_failures": monitor.consecutive_failures,
        "threshold": monitor.alert_threshold_failures,
        "region": region,
        "error_message": error_message,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "app_url": f"{settings.SITE_URL}/project/{monitor.team_id}/synthetic-monitoring/{monitor.id}",
    }

    # Send email notifications
    if monitor.alert_recipients.exists():
        send_email_alert(monitor, alert_context)

    # Send Slack notification
    if monitor.slack_integration:
        send_slack_alert(monitor, alert_context)

    # Update last_alerted_at
    monitor.last_alerted_at = datetime.now(UTC)
    monitor.save(update_fields=["last_alerted_at"])

    # Report usage event
    report_team_action(
        monitor.team,
        "synthetic monitor alert sent",
        {
            "monitor_id": str(monitor.id),
            "consecutive_failures": monitor.consecutive_failures,
        },
    )

    logger.info("Synthetic monitor alert sent", monitor_id=str(monitor.id))


def send_email_alert(monitor: SyntheticMonitor, context: dict[str, Any]) -> None:
    """Send email alert to configured recipients"""
    subject = f"[PostHog Alert] Synthetic Monitor Failing: {monitor.name}"

    for recipient in monitor.alert_recipients.all():
        try:
            message = EmailMessage(
                campaign_key=f"synthetic-monitor-alert-{monitor.id}-{datetime.now(UTC).timestamp()}",
                subject=subject,
                template_name="synthetic_monitor_alert",
                template_context={
                    "user_name": recipient.first_name or recipient.email,
                    **context,
                },
            )
            message.add_recipient(email=recipient.email, name=recipient.first_name or recipient.email)
            message.send()

            logger.info(
                "Email alert sent",
                monitor_id=str(monitor.id),
                recipient=recipient.email,
            )
        except Exception as e:
            logger.exception(
                "Failed to send email alert",
                monitor_id=str(monitor.id),
                recipient=recipient.email,
                error=str(e),
            )


def send_slack_alert(monitor: SyntheticMonitor, context: dict[str, Any]) -> None:
    """Send Slack alert via integration"""
    if not monitor.slack_integration or monitor.slack_integration.kind != "slack":
        return

    try:
        integration_config = monitor.slack_integration.config or {}
        webhook_url = integration_config.get("webhook_url")

        if not webhook_url:
            logger.error("Slack webhook URL not configured", monitor_id=str(monitor.id))
            return

        # Build Slack message
        message = {
            "text": f":warning: Synthetic Monitor Alert: {monitor.name}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":warning: Synthetic Monitor Failing: {monitor.name}",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*URL:*\n{context['monitor_url']}"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Failures:*\n{context['consecutive_failures']}/{context['threshold']}",
                        },
                        {"type": "mrkdwn", "text": f"*Region:*\n{context['region']}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Error:* {context['error_message']}"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View Monitor"},
                            "url": context["app_url"],
                        }
                    ],
                },
            ],
        }

        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()

        logger.info("Slack alert sent", monitor_id=str(monitor.id))
    except Exception as e:
        logger.exception(
            "Failed to send Slack alert",
            monitor_id=str(monitor.id),
            error=str(e),
        )
