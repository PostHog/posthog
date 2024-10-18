import math
import time
import traceback

from datetime import datetime, timedelta, UTC
from typing import cast
from dateutil.relativedelta import relativedelta

from celery import shared_task
from celery.canvas import chain
from django.conf import settings
from django.db import transaction
import structlog
from sentry_sdk import capture_exception

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import (
    conversion_to_query_based,
)
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.tasks.utils import CeleryQueue
from posthog.schema import (
    TrendsQuery,
    AlertCalculationInterval,
    AlertState,
)
from posthog.utils import get_from_dict_or_attr
from prometheus_client import Counter, Gauge
from django.db.models import Q, F
from collections import defaultdict
from posthog.tasks.alerts.utils import (
    AlertEvaluationResult,
    calculation_interval_to_order,
    send_notifications_for_errors,
    send_notifications_for_breaches,
    WRAPPER_NODE_KINDS,
    alert_calculation_interval_to_relativedelta,
)
from posthog.tasks.alerts.trends import check_trends_alert


logger = structlog.get_logger(__name__)


class AlertCheckException(Exception):
    """
    Required for custom exceptions to pass stack trace to sentry.
    Subclassing through other ways doesn't transfer the traceback.
    https://stackoverflow.com/a/69963663/5540417
    """

    def __init__(self, err: Exception):
        self.__traceback__ = err.__traceback__


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

ALERT_COMPUTED_COUNTER = Counter(
    "alerts_computed",
    "Number of alerts we calculated",
)


@shared_task(ignore_result=True)
def checks_cleanup_task() -> None:
    AlertCheck.clean_up_old_checks()


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

    # sleeping 30s for prometheus to pick up the metrics sent during task
    time.sleep(30)


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def check_alerts_task() -> None:
    """
    This runs every 2min to check for alerts that are due to recalculate
    """
    now = datetime.now(UTC)
    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = now + timedelta(minutes=30)

    # find all alerts with the provided interval that are due to be calculated
    # (next_check_at is null or less than now) and it's not snoozed
    alerts = (
        AlertConfiguration.objects.filter(
            Q(enabled=True, is_calculating=False, next_check_at__lte=now)
            | Q(enabled=True, is_calculating=False, next_check_at__isnull=True)
        )
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
        .order_by(F("next_check_at").asc(nulls_first=True))
        .only("id", "team", "calculation_interval")
    )

    sorted_alerts = sorted(
        alerts,
        key=lambda alert: calculation_interval_to_order(
            cast(AlertCalculationInterval | None, alert.calculation_interval)
        ),
    )

    grouped_by_team = defaultdict(list)
    for alert in sorted_alerts:
        grouped_by_team[alert.team].append(alert.id)

    for alert_ids in grouped_by_team.values():
        # We chain the task execution to prevent queries *for a single team* running at the same time
        chain(*(check_alert_task.si(str(alert_id)).set(expires=expire_after) for alert_id in alert_ids))()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ALERTS.value,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=1,
    retry_backoff_max=10,
    max_retries=3,
    expires=60 * 60,
)
# @limit_concurrency(5)  Concurrency controlled by CeleryQueue.ALERTS for now
def check_alert_task(alert_id: str) -> None:
    check_alert(alert_id)


def check_alert(alert_id: str) -> None:
    task_start_time = time.time()

    try:
        alert = AlertConfiguration.objects.get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    now = datetime.now(UTC)
    if alert.next_check_at and alert.next_check_at > now:
        logger.warning(
            """Alert took too long to compute or was queued too long during which it already got computed.
            So not attempting to compute it again until it's due next""",
            alert=alert,
        )
        return

    if alert.is_calculating:
        logger.warning(
            "Alert is already being computed so skipping checking it now",
            alert=alert,
        )
        return

    if alert.snoozed_until:
        if alert.snoozed_until > now:
            logger.warning(
                "Alert has been snoozed so skipping checking it now",
                alert=alert,
            )
            return
        else:
            # not snoozed (anymore) so clear snoozed_until
            alert.snoozed_until = None
            alert.state = AlertState.NOT_FIRING

    alert.is_calculating = True
    alert.save()

    try:
        check_alert_and_notify_atomically(alert)
    except Exception as err:
        ALERT_CHECK_ERROR_COUNTER.inc()

        logger.exception(AlertCheckException(err))
        capture_exception(
            AlertCheckException(err),
            tags={
                "alert_configuration_id": alert_id,
            },
        )

        # raise again so alert check is retried depending on error type
        raise
    finally:
        # Get all updates with alert checks
        alert.refresh_from_db()
        alert.is_calculating = False
        alert.save()

        # only in PROD
        if not settings.DEBUG and not settings.TEST:
            task_duration = time.time() - task_start_time

            # Ensure task runs at least 40s
            # for prometheus to pick up the metrics sent during task
            time_left_to_run = 40 - math.floor(task_duration)
            time.sleep(time_left_to_run)


@transaction.atomic
def check_alert_and_notify_atomically(alert: AlertConfiguration) -> None:
    """
    Computes insight results, checks alert for breaches and notifies user.
    Only commits updates to alert state if all of the above complete successfully.
    TODO: Later separate notification mechanism from alert checking mechanism (when we move to CDP)
        so we can retry notification without re-computing insight.
    """
    ALERT_COMPUTED_COUNTER.inc()
    value = breaches = error = None

    # 1. Evaluate insight and get alert value
    try:
        alert_evaluation_result = check_alert_for_insight(alert)
        value = alert_evaluation_result.value
        breaches = alert_evaluation_result.breaches
    except CHQueryErrorTooManySimultaneousQueries:
        # error on our side so we raise
        # as celery task can be retried according to config
        raise
    except Exception as err:
        capture_exception(AlertCheckException(err))
        # error can be on user side (incorrectly configured insight/alert)
        # we won't retry and set alert to errored state
        error = {"message": str(err), "traceback": traceback.format_exc()}

    # 2. Check alert value against threshold
    alert_check = add_alert_check(alert, value, breaches, error)

    # 3. Notify users if needed
    if not alert_check.targets_notified:
        return

    try:
        match alert_check.state:
            case AlertState.NOT_FIRING:
                logger.info("Check state is %s", alert_check.state, alert_id=alert.id)
            case AlertState.ERRORED:
                send_notifications_for_errors(alert, alert_check.error)
            case AlertState.FIRING:
                assert breaches is not None
                send_notifications_for_breaches(alert, breaches)
    except Exception as err:
        error_message = f"AlertCheckError: error sending notifications for alert_id = {alert.id}"
        logger.exception(error_message)

        capture_exception(
            Exception(error_message),
            {"alert_id": alert.id, "message": str(err)},
        )

        # don't want alert state to be updated (so that it's retried as next_check_at won't be updated)
        # so we raise again as @transaction.atomic decorator won't commit db updates
        # TODO: later should have a way just to retry notification mechanism
        raise


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """
    Matches insight type with alert checking logic
    """
    insight = alert.insight

    with conversion_to_query_based(insight):
        query = insight.query
        kind = get_from_dict_or_attr(query, "kind")

        if kind in WRAPPER_NODE_KINDS:
            query = get_from_dict_or_attr(query, "source")
            kind = get_from_dict_or_attr(query, "kind")

        match kind:
            case "TrendsQuery":
                query = TrendsQuery.model_validate(query)
                return check_trends_alert(alert, insight, query)
            case _:
                raise NotImplementedError(f"AlertCheckError: Alerts for {query.kind} are not supported yet")


def add_alert_check(
    alert: AlertConfiguration, value: float | None, breaches: list[str] | None, error: dict | None
) -> AlertCheck:
    notify = False
    targets_notified = {}

    if error:
        alert.state = AlertState.ERRORED
        notify = True
    elif breaches:
        alert.state = AlertState.FIRING
        notify = True
    else:
        alert.state = AlertState.NOT_FIRING  # Set the Alert to not firing if the threshold is no longer met
        # TODO: Optionally send a resolved notification when alert goes from firing to not_firing?

    now = datetime.now(UTC)
    alert.last_checked_at = datetime.now(UTC)

    # IMPORTANT: update next_check_at according to interval
    # ensure we don't recheck alert until the next interval is due
    alert.next_check_at = (alert.next_check_at or now) + alert_calculation_interval_to_relativedelta(
        cast(AlertCalculationInterval, alert.calculation_interval)
    )

    if notify:
        alert.last_notified_at = now
        targets_notified = {"users": list(alert.subscribed_users.all().values_list("email", flat=True))}

    alert_check = AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=value,
        condition=alert.condition,
        targets_notified=targets_notified,
        state=alert.state,
        error=error,
    )

    alert.save()

    return alert_check
