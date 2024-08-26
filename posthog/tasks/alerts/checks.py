from datetime import datetime, timedelta, UTC
from typing import Optional

from celery import shared_task
from celery.canvas import chain
from django.db import transaction
from django.utils import timezone
import structlog
from sentry_sdk import capture_exception

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.email import EmailMessage
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import (
    conversion_to_query_based,
)
from posthog.models import AlertConfiguration, Team
from posthog.models.alert import AlertCheck
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


def check_all_alerts() -> None:
    # TODO: Consider aligning insight calculation with cache warming of insights, see warming.py
    # Currently it's implicitly aligned by alerts obviously also using cache if available

    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = datetime.now(UTC) + timedelta(minutes=30)

    teams = Team.objects.filter(alertconfiguration__isnull=False).distinct()

    for team in teams:
        alert_ids = list(AlertConfiguration.objects.filter(team=team, enabled=True).values_list("id", flat=True))

        # We chain the task execution to prevent queries *for a single team* running at the same time
        chain(*(check_alert_task.si(alert_id).set(expires=expire_after) for alert_id in alert_ids))()


@transaction.atomic
def check_alert(alert_id: int) -> None:
    try:
        alert = AlertConfiguration.objects.select_for_update().get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    insight = alert.insight
    error: Optional[dict] = None

    try:
        with conversion_to_query_based(insight):
            calculation_result = calculate_for_query_based_insight(
                insight,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=None,
            )

        if not calculation_result.result:
            raise RuntimeError(f"No results for alert {alert.id}")

        result = calculation_result.result[0]
        aggregated_value = result["aggregated_value"]
    except Exception as e:
        event_id = capture_exception(e)
        error = {
            "sentry_event_id": event_id,
            "message": str(e),
        }
        aggregated_value = None

    check, matches = alert.add_check(calculated_value=aggregated_value, error=error)

    if not check.state == "firing":
        logger.info("Check state is %s", check.state, alert_id=alert.id)
        return

    if not matches:
        # We might be firing but have no (new) matches to notify about
        return

    send_notifications(alert, matches)


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def check_all_alerts_task() -> None:
    check_all_alerts()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ANALYTICS_LIMITED.value,  # Important! Prevents Clickhouse from being overwhelmed
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=1,
    retry_backoff_max=10,
    max_retries=10,
    expires=60 * 60,
)
def check_alert_task(alert_id: int) -> None:
    check_alert(alert_id)


@shared_task(ignore_result=True)
def checks_cleanup_task() -> None:
    AlertCheck.clean_up_old_checks()


def send_notifications(alert: AlertConfiguration, matches: list[str]) -> None:
    subject = f"PostHog alert {alert.name} is firing"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}/alerts/{alert.id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": matches,
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "alert_url": alert_url,
            "alert_name": alert.name,
        },
    )
    targets = alert.subscribed_users.all().values_list("email", flat=True)
    if not targets:
        raise RuntimeError(f"no targets configured for the alert {alert.id}")
    for target in targets:
        message.add_recipient(email=target)

    logger.info(f"Send notifications about {len(matches)} anomalies", alert_id=alert.id)
    message.send()
