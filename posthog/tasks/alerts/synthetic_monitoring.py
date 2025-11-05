"""
Celery tasks for synthetic monitoring alerting and check scheduling.
"""

import time
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

import requests
import structlog
from celery import shared_task

from posthog.api.capture import capture_internal
from posthog.email import EmailMessage
from posthog.event_usage import report_team_action
from posthog.models import SyntheticMonitor
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


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
        try:
            execute_http_check.delay(monitor_id=str(monitor.id))
        except Exception as e:
            logger.exception(
                "Failed to trigger check",
                monitor_id=str(monitor.id),
                error=str(e),
            )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=3,
)
def execute_http_check(monitor_id: str, region: str = "default") -> None:
    """
    Execute an HTTP check for a synthetic monitor.
    Makes the HTTP request, records the result, and emits event to PostHog.
    """
    try:
        monitor = SyntheticMonitor.objects.select_related("team").get(id=monitor_id)
    except SyntheticMonitor.DoesNotExist:
        logger.exception("Monitor not found", monitor_id=monitor_id)
        return

    # Execute the HTTP check
    start_time = time.time()
    success = False
    status_code = None
    error_message = None
    response_time_ms = None

    try:
        # Prepare request
        headers = monitor.headers or {}
        timeout = monitor.timeout_seconds

        # Make HTTP request
        response = requests.request(
            method=monitor.method,
            url=monitor.url,
            headers=headers,
            data=monitor.body if monitor.body else None,
            timeout=timeout,
            allow_redirects=True,
        )

        # Calculate response time
        response_time_ms = int((time.time() - start_time) * 1000)
        status_code = response.status_code

        # Check if status code matches expected
        success = status_code == monitor.expected_status_code

        if not success:
            error_message = f"Expected status code {monitor.expected_status_code}, got {status_code}"

        logger.info(
            "HTTP check completed",
            monitor_id=str(monitor.id),
            url=monitor.url,
            success=success,
            status_code=status_code,
            response_time_ms=response_time_ms,
        )

    except requests.exceptions.Timeout:
        response_time_ms = monitor.timeout_seconds * 1000
        error_message = f"Request timed out after {monitor.timeout_seconds} seconds"
        logger.warning("HTTP check timeout", monitor_id=str(monitor.id), url=monitor.url)

    except requests.exceptions.RequestException as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        error_message = str(e)
        logger.warning("HTTP check failed", monitor_id=str(monitor.id), url=monitor.url, error=str(e))

    except Exception as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        error_message = f"Unexpected error: {str(e)}"
        logger.exception("HTTP check error", monitor_id=str(monitor.id), url=monitor.url, error=str(e))

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
