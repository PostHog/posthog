from dateutil.relativedelta import relativedelta, MO
from django.utils import timezone
import pytz

from datetime import datetime
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


def next_check_time(alert: AlertConfiguration) -> datetime:
    """
    Rule by calculation interval

    hourly alerts -> want them to run at the same min every hour (same min comes from creation time so that they're spread out and don't all run at the start of the hour)
    daily alerts -> want them to run at the start of the day (around 1am) by the timezone of the team
    weekly alerts -> want them to run at the start of the week (Mon around 3am) by the timezone of the team
    monthly alerts -> want them to run at the start of the month (first day of the month around 4am) by the timezone of the team
    """
    now = datetime.now(pytz.UTC)
    team_timezone = pytz.timezone(alert.team.timezone)

    match alert.calculation_interval:
        case AlertCalculationInterval.HOURLY:
            return (alert.next_check_at or now) + relativedelta(hours=1)
        case AlertCalculationInterval.DAILY:
            # Get the next date in the specified timezone
            tomorrow_local = datetime.now(team_timezone) + relativedelta(days=1)

            # set hour to 1 AM
            # only replacing hour and not minute/second... to distribute execution of all daily alerts
            one_am_local = tomorrow_local.replace(hour=1)

            # Convert to UTC
            return one_am_local.astimezone(pytz.utc)
        case AlertCalculationInterval.WEEKLY:
            next_monday_local = datetime.now(team_timezone) + relativedelta(days=1, weekday=MO(1))

            # Set the hour to around 3 AM on next Monday
            next_monday_1am_local = next_monday_local.replace(hour=3)

            # Convert to UTC
            return next_monday_1am_local.astimezone(pytz.utc)
        case AlertCalculationInterval.MONTHLY:
            next_month_local = datetime.now(team_timezone) + relativedelta(months=1)

            # Set hour to 4 AM on first day of next month
            next_month_1am_local = next_month_local.replace(day=1, hour=4)

            # Convert to UTC
            return next_month_1am_local.astimezone(pytz.utc)
        case _:
            raise ValueError(f"Invalid alert calculation interval: {alert.calculation_interval}")


def send_notifications_for_breaches(alert: AlertConfiguration, breaches: list[str]) -> None:
    subject = f"PostHog alert {alert.name} is firing"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}?alert_id={alert.id}"
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
    logger.info("Sending alert error notifications", alert_id=alert.id, error=error)

    # TODO: uncomment this after checking errors sent
    # subject = f"PostHog alert {alert.name} check failed to evaluate"
    # campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    # insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    # alert_url = f"{insight_url}?alert_id={alert.id}"
    # message = EmailMessage(
    #     campaign_key=campaign_key,
    #     subject=subject,
    #     template_name="alert_check_failed_to_evaluate",
    #     template_context={
    #         "alert_error": error,
    #         "insight_url": insight_url,
    #         "insight_name": alert.insight.name,
    #         "alert_url": alert_url,
    #         "alert_name": alert.name,
    #     },
    # )
    # targets = alert.subscribed_users.all().values_list("email", flat=True)
    # if not targets:
    #     raise RuntimeError(f"no targets configured for the alert {alert.id}")
    # for target in targets:
    #     message.add_recipient(email=target)

    # message.send()
