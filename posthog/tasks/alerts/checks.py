from datetime import datetime, timedelta, UTC
from typing import Optional
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
from posthog.models import AlertConfiguration, Team
from posthog.models.alert import AlertCheck
from posthog.tasks.utils import CeleryQueue
from posthog.schema import TrendsQuery, IntervalType, ChartDisplayType, NodeKind
from posthog.utils import get_from_dict_or_attr
from posthog.caching.fetch_from_cache import InsightResult

logger = structlog.get_logger(__name__)


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
def hourly_alerts_task() -> None:
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
def check_alert_task(alert_id: str) -> None:
    check_alert(alert_id)


@shared_task(ignore_result=True)
def checks_cleanup_task() -> None:
    AlertCheck.clean_up_old_checks()


def check_all_alerts() -> None:
    # TODO: Consider aligning insight calculation with cache warming of insights, see warming.py
    # Currently it's implicitly aligned by alerts obviously also using cache if available

    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = datetime.now(UTC) + timedelta(minutes=30)

    teams = Team.objects.filter(alertconfiguration__isnull=False).distinct()

    for team in teams:
        alert_ids = list(AlertConfiguration.objects.filter(team=team, enabled=True).values_list("id", flat=True))

        # We chain the task execution to prevent queries *for a single team* running at the same time
        chain(*(check_alert_task.si(str(alert_id)).set(expires=expire_after) for alert_id in alert_ids))()


WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]


@transaction.atomic
def check_alert(alert_id: str) -> None:
    try:
        alert = AlertConfiguration.objects.get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    insight = alert.insight
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

                filters_override = _calculate_date_range_override_for_alert(query)

                # now override interval to be daily so we can get calculate an aggregated value for
                # alert checking window
                insight.query["source"]["interval"] = IntervalType.DAY

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

        aggregated_value = _aggregate_insight_result_value(alert, query, filters_override, calculation_result)
    except Exception as e:
        # TODO: judging by exception we need to retry. Like if too many simultaneous queries
        # maybe should handle in celery logic instead of here
        event_id = capture_exception(e)
        error = {
            "sentry_event_id": event_id,
            "message": str(e),
        }
        aggregated_value = None

    # Lock alert to prevent concurrent state changes
    alert = AlertConfiguration.objects.select_for_update().get(id=alert_id, enabled=True)
    check, matches = alert.add_check(aggregated_value=aggregated_value, error=error)

    if not check.state == "firing":
        logger.info("Check state is %s", check.state, alert_id=alert.id)
        return

    if not matches:
        # We might be firing but have no (new) matches to notify about
        return

    _send_notifications(alert, matches)


def _calculate_date_range_override_for_alert(query: TrendsQuery) -> Optional[dict]:
    if query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES:
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


def _aggregate_insight_result_value(
    alert: AlertConfiguration, query: TrendsQuery, filters_override: dict, results: InsightResult
) -> float:
    series_index = alert.series_index
    result = results.result[series_index]

    if query.trendsFilter.display in NON_TIME_SERIES_DISPLAY_TYPES:
        return result["aggregated_value"]

    date_from = filters_override["date_from"]
    now = datetime.now(UTC)
    start_datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)

    match date_from:
        case "-1d":
            start_datetime -= timedelta(days=1)
        case "-1w":
            start_datetime -= timedelta(days=7)
        case "-1m":
            start_datetime -= relativedelta(months=1)
        case "-1h":
            start_datetime -= timedelta(hours=1)

    aggregate_value = 0

    for day, data in zip(result["days"], result["data"]):
        date = datetime.strptime(
            day, "%Y-%m-%d{}".format(" %H:%M:%S" if query.interval == IntervalType.HOUR else "")
        ).replace(tzinfo=UTC)

        if start_datetime <= date <= now:
            aggregate_value += data

    return aggregate_value


def _send_notifications(alert: AlertConfiguration, matches: list[str]) -> None:
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
