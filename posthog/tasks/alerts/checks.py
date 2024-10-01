from datetime import datetime, timedelta, UTC
from typing import Optional, cast
from dateutil.relativedelta import relativedelta

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
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.tasks.utils import CeleryQueue
from posthog.schema import (
    TrendsQuery,
    IntervalType,
    ChartDisplayType,
    NodeKind,
    AlertCalculationInterval,
    AlertState,
    TrendsAlertConfig,
)
from posthog.utils import get_from_dict_or_attr
from posthog.caching.fetch_from_cache import InsightResult
from posthog.clickhouse.client.limit import limit_concurrency
from prometheus_client import Counter, Gauge
from django.db.models import Q
from typing import TypedDict, NotRequired
from collections import defaultdict


# TODO: move the TrendResult UI type to schema.ts and use that instead
class TrendResult(TypedDict):
    action: dict
    actions: list[dict]
    count: int
    data: list[float]
    days: list[str]
    dates: list[str]
    label: str
    labels: list[str]
    breakdown_value: str | int | list[str]
    aggregated_value: NotRequired[float]
    status: str | None
    compare_label: str | None
    compare: bool
    persons_urls: list[dict]
    persons: dict
    filter: dict


HOURLY_ALERTS_BACKLOG_GAUGE = Gauge(
    "hourly_alerts_backlog",
    "Number of hourly alerts that are not being checked in the last hour.",
)

DAILY_ALERTS_BACKLOG_GAUGE = Gauge(
    "daily_alerts_backlog",
    "Number of daily alerts that are not being checked in the last 24 hours.",
)

ALERT_CHECK_ERROR_COUNTER = Counter(
    "alerts_check_failures",
    "Number of alert check errors that don't notify the user",
)

ALERT_CHECK_COUNTER = Counter(
    "alerts_check",
    "Number of alerts we tried to check",
    labelnames=["interval"],
)


logger = structlog.get_logger(__name__)


WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

NON_TIME_SERIES_DISPLAY_TYPES = {
    ChartDisplayType.BOLD_NUMBER,
    ChartDisplayType.ACTIONS_PIE,
    ChartDisplayType.ACTIONS_BAR_VALUE,
    ChartDisplayType.ACTIONS_TABLE,
    ChartDisplayType.WORLD_MAP,
}


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def alerts_backlog_task() -> None:
    """
    This runs every 5min to check backlog for alerts
    - hourly alerts - alerts that haven't been checked in the last hour + 5min
    - daily alerts - alerts that haven't been checked in the last hour + 15min
    """
    now = datetime.now(UTC)

    hourly_alerts_breaching_sla = AlertConfiguration.objects.filter(
        Q(
            enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
            last_checked_at__lte=now - relativedelta(hours=1, minutes=5),
        )
    ).count()

    HOURLY_ALERTS_BACKLOG_GAUGE.set(hourly_alerts_breaching_sla)

    now = datetime.now(UTC)

    daily_alerts_breaching_sla = AlertConfiguration.objects.filter(
        Q(
            enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
            last_checked_at__lte=now - relativedelta(days=1, minutes=15),
        )
    ).count()

    DAILY_ALERTS_BACKLOG_GAUGE.set(daily_alerts_breaching_sla)


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def hourly_alerts_task() -> None:
    """
    This runs every 2min to check for alerts that are due to recalculate
    """
    check_alerts(AlertCalculationInterval.HOURLY)


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def daily_alerts_task() -> None:
    """
    This runs every 10min to check for alerts that are due to recalculate
    """
    check_alerts(AlertCalculationInterval.DAILY)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ALERTS.value,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=1,
    retry_backoff_max=10,
    max_retries=3,
    expires=60 * 60,
)
@limit_concurrency(5)  # Max 5 concurrent alert checks
def check_alert_task(alert_id: str) -> None:
    try:
        check_alert(alert_id)
    except Exception as err:
        ALERT_CHECK_ERROR_COUNTER.inc()
        capture_exception(Exception(f"Error checking alert, user wasn't notified: {err}"))
        raise


@shared_task(ignore_result=True)
def checks_cleanup_task() -> None:
    AlertCheck.clean_up_old_checks()


def check_alerts(interval: AlertCalculationInterval) -> None:
    now = datetime.now(UTC)
    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = now + timedelta(minutes=30)

    # find all alerts with the provided interval that are due to be calculated (next_check_at is null or less than now)
    alerts = AlertConfiguration.objects.filter(
        Q(enabled=True, calculation_interval=interval, next_check_at__lte=now)
        | Q(
            enabled=True,
            calculation_interval=interval,
            next_check_at__isnull=True,
        )
    ).only("id", "team")

    grouped_by_team = defaultdict(list)
    for alert in alerts:
        grouped_by_team[alert.team].append(alert.id)

    for alert_ids in grouped_by_team.values():
        # We chain the task execution to prevent queries *for a single team* running at the same time
        chain(*(check_alert_task.si(str(alert_id)).set(expires=expire_after) for alert_id in alert_ids))()


@transaction.atomic
def check_alert(alert_id: str) -> None:
    try:
        alert = AlertConfiguration.objects.get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    ALERT_CHECK_COUNTER.labels(interval=alert.calculation_interval).inc()

    now = datetime.now(UTC)
    if alert.next_check_at > now:
        logger.warning(
            """Alert took too long to compute or was queued too long during which it already got computed.
            So not attempting to compute it again until it's due next""",
            alert=alert,
        )
        return

    insight = alert.insight
    aggregated_value: Optional[float] = None
    error: Optional[dict] = None

    try:
        with conversion_to_query_based(insight):
            query = insight.query
            kind = get_from_dict_or_attr(query, "kind")

            if kind in WRAPPER_NODE_KINDS:
                query = get_from_dict_or_attr(query, "source")
                kind = get_from_dict_or_attr(query, "kind")

            if kind == "TrendsQuery":
                query = TrendsQuery.model_validate(query)
                alert.config = TrendsAlertConfig.model_validate(alert.config)

                filters_override = _calculate_date_range_override_for_alert(query)

                calculation_result = calculate_for_query_based_insight(
                    insight,
                    execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                    user=None,
                    filters_override=filters_override,
                )
            else:
                raise NotImplementedError(f"Alerts for {query.kind} are not supported yet")

        if not calculation_result.result:
            raise RuntimeError(f"No results for alert {alert.id}")

        aggregated_value = _aggregate_insight_result_value(alert, query, calculation_result)
    except CHQueryErrorTooManySimultaneousQueries:
        # error on our side, need to make sure to retry the alert check
        raise
    except Exception as err:
        # error possibly on user's config side
        # notify user that alert check errored
        event_id = capture_exception(err)
        error = {
            "sentry_event_id": event_id,
            "message": str(err),
        }

    # Lock alert to prevent concurrent state changes
    alert = AlertConfiguration.objects.select_for_update().get(id=alert_id, enabled=True)
    check, breaches, error, notify = alert.add_check(aggregated_value=aggregated_value, error=error)

    if not notify:
        # no need to notify users
        return

    match check.state:
        case AlertState.NOT_FIRING:
            logger.info("Check state is %s", check.state, alert_id=alert.id)
        case AlertState.ERRORED:
            if error:
                _send_notifications_for_errors(alert, error)
        case AlertState.FIRING:
            _send_notifications_for_breaches(alert, breaches)


def _calculate_date_range_override_for_alert(query: TrendsQuery) -> Optional[dict]:
    if query.trendsFilter and query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES:
        # for single value insights, need to recompute with full time range
        return None

    match query.interval:
        case IntervalType.DAY:
            date_from = "-1d"
        case IntervalType.WEEK:
            date_from = "-1w"
        case IntervalType.MONTH:
            date_from = "-1m"
        case _:
            date_from = "-1h"

    return {"date_from": date_from}


def _aggregate_insight_result_value(alert: AlertConfiguration, query: TrendsQuery, results: InsightResult) -> float:
    if alert.config.type == "TrendsAlertConfig":
        alert.config = cast(TrendsAlertConfig, alert.config)
        series_index = alert.config.series_index
        result = cast(list[TrendResult], results.result)[series_index]

        if query.trendsFilter and query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES:
            return result["aggregated_value"]

        return result["data"][-1]

    raise ValueError(f"Unsupported alert config type: {alert.config.type}")


def _send_notifications_for_breaches(alert: AlertConfiguration, breaches: list[str]) -> None:
    subject = f"PostHog alert {alert.name} is firing"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
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


def _send_notifications_for_errors(alert: AlertConfiguration, error: dict) -> None:
    subject = f"PostHog alert {alert.name} check failed to evaluate"
    campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
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
