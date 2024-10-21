from dateutil.relativedelta import relativedelta

from django.utils import timezone
import structlog

from posthog.email import EmailMessage
from posthog.models import AlertConfiguration
from posthog.schema import (
    ChartDisplayType,
    NodeKind,
    AlertCalculationInterval,
)
from dataclasses import dataclass

logger = structlog.get_logger(__name__)


@dataclass
class AlertEvaluationResult:
    value: float | None
    breaches: list[str] | None


WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

NON_TIME_SERIES_DISPLAY_TYPES = {
    ChartDisplayType.BOLD_NUMBER,
    ChartDisplayType.ACTIONS_PIE,
    ChartDisplayType.ACTIONS_BAR_VALUE,
    ChartDisplayType.ACTIONS_TABLE,
    ChartDisplayType.WORLD_MAP,
}


def calculation_interval_to_order(interval: AlertCalculationInterval | None) -> int:
    match interval:
        case AlertCalculationInterval.HOURLY:
            return 0
        case AlertCalculationInterval.DAILY:
            return 1
        case _:
            return 2


def alert_calculation_interval_to_relativedelta(alert_calculation_interval: AlertCalculationInterval) -> relativedelta:
    match alert_calculation_interval:
        case AlertCalculationInterval.HOURLY:
            return relativedelta(hours=1)
        case AlertCalculationInterval.DAILY:
            return relativedelta(days=1)
        case AlertCalculationInterval.WEEKLY:
            return relativedelta(weeks=1)
        case AlertCalculationInterval.MONTHLY:
            return relativedelta(months=1)
        case _:
            raise ValueError(f"Invalid alert calculation interval: {alert_calculation_interval}")


def send_notifications_for_breaches(alert: AlertConfiguration, breaches: list[str]) -> None:
    subject = f"PostHog alert {alert.name} is firing"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}?alert_id={alert.id}"
    alert_url = f"{insight_url}/alerts/{alert.id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": breaches,
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

    logger.info(f"Send notifications about {len(breaches)} anomalies", alert_id=alert.id)
    message.send()


def send_notifications_for_errors(alert: AlertConfiguration, error: dict) -> None:
    subject = f"PostHog alert {alert.name} check failed to evaluate"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}?alert_id={alert.id}"
    alert_url = f"{insight_url}/alerts/{alert.id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": error,
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

    logger.info(f"Send notifications about alert checking error", alert_id=alert.id)
    message.send()
