import traceback

from datetime import datetime, timedelta, UTC
from typing import cast
from collections.abc import Callable
from dateutil.relativedelta import relativedelta

from celery import shared_task
from celery.canvas import chain
from django.db import transaction
from posthog.schema_migrations.upgrade_manager import upgrade_query
import structlog
from posthog.clickhouse.query_tagging import tag_queries

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.exceptions_capture import capture_exception
from posthog.models import AlertConfiguration, User
from posthog.models.alert import AlertCheck
from posthog.tasks.utils import CeleryQueue
from posthog.schema import (
    TrendsQuery,
    AlertCalculationInterval,
    AlertState,
)
from posthog.utils import get_from_dict_or_attr
from django.db.models import Q, F
from collections import defaultdict
from posthog.tasks.alerts.utils import (
    AlertEvaluationResult,
    calculation_interval_to_order,
    next_check_time,
    send_notifications_for_breaches,
    send_notifications_for_errors,
    skip_because_of_weekend,
    WRAPPER_NODE_KINDS,
)
from posthog.tasks.alerts.trends import check_trends_alert
from posthog.ph_client import ph_scoped_capture


logger = structlog.get_logger(__name__)


class AlertCheckException(Exception):
    """
    Required for custom exceptions to pass stack trace to error tracking.
    Subclassing through other ways doesn't transfer the traceback.
    https://stackoverflow.com/a/69963663/5540417
    """

    def __init__(self, err: Exception):
        self.__traceback__ = err.__traceback__


ANIRUDH_DISTINCT_ID = "wcPbDRs08GtNzrNIXfzHvYAkwUaekW7UrAo4y3coznT"


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

    now = datetime.now(UTC)

    daily_alerts_breaching_sla = AlertConfiguration.objects.filter(
        Q(
            enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
            last_checked_at__lte=now - relativedelta(days=1, minutes=15),
        )
    ).count()

    with ph_scoped_capture() as capture_ph_event:
        capture_ph_event(
            distinct_id=ANIRUDH_DISTINCT_ID,
            event="alert check backlog",
            properties={
                "calculation_interval": AlertCalculationInterval.DAILY,
                "backlog": daily_alerts_breaching_sla,
            },
        )

        capture_ph_event(
            distinct_id=ANIRUDH_DISTINCT_ID,
            event="alert check backlog",
            properties={
                "calculation_interval": AlertCalculationInterval.HOURLY,
                "backlog": hourly_alerts_breaching_sla,
            },
        )


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def reset_stuck_alerts_task() -> None:
    now = datetime.now(UTC)

    # TRICKY: When celery task exits due to timeout/insight calc taking too long
    # the finally block below isn't run and the alert gets stuck with is_calculating = True
    # hence when checking is_calculating, we also need to check if task has been stuck in is_calculating for too long
    stuck_alerts = AlertConfiguration.objects.filter(
        Q(enabled=True, is_calculating=True, last_checked_at__lte=now - relativedelta(minutes=45))
        | Q(
            enabled=True,
            is_calculating=True,
            last_checked_at__isnull=True,
            created_at__lte=now - relativedelta(minutes=45),
        )
    )

    for alert in stuck_alerts:
        # we need to check the alert, reset is_calculating
        logger.info(f"Alert {alert.id} is stuck in is_calculating for too long, resetting is_calculating")
        alert.is_calculating = False
        alert.save()


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
    with ph_scoped_capture() as capture_ph_event:
        check_alert(alert_id, capture_ph_event)


def check_alert(alert_id: str, capture_ph_event: Callable = lambda *args, **kwargs: None) -> None:
    try:
        alert = AlertConfiguration.objects.get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    now = datetime.now(UTC)

    if alert.next_check_at and alert.next_check_at > now:
        logger.info(
            """Alert took too long to compute or was queued too long during which it already got computed.
            So not attempting to compute it again until it's due next""",
            alert=alert,
        )
        return

    if alert.is_calculating:
        logger.info(
            "Alert is already being computed so skipping checking it now",
            alert=alert,
        )
        return

    if skip_because_of_weekend(alert):
        logger.info(
            "Skipping alert check because weekend checking is disabled",
            alert=alert,
        )

        # ignore alert check until due again
        alert.next_check_at = next_check_time(alert)
        alert.save()
        return

    if alert.snoozed_until:
        if alert.snoozed_until > now:
            logger.info(
                "Alert has been snoozed so skipping checking it now",
                alert=alert,
            )
            return
        else:
            # not snoozed (anymore) so clear snoozed_until
            alert.snoozed_until = None
            alert.state = AlertState.NOT_FIRING

    # we will attempt to check alert
    logger.info(f"Checking alert id = {alert.id}")
    alert.last_checked_at = datetime.now(UTC)
    alert.is_calculating = True
    alert.save()

    try:
        check_alert_and_notify_atomically(alert, capture_ph_event)
    except Exception as err:
        user = cast(User, alert.created_by)

        capture_ph_event(
            distinct_id=user.distinct_id,
            event="alert check failed",
            properties={
                "alert_id": alert.id,
                "error": f"AlertCheckError: {err}",
                "traceback": traceback.format_exc(),
            },
        )

        logger.exception(AlertCheckException(err))
        capture_exception(
            AlertCheckException(err),
            additional_properties={
                "alert_configuration_id": alert_id,
            },
        )

        # raise again so alert check is retried depending on error type
        raise
    finally:
        # TRICKY: When celery task exits due to timeout/insight calc taking too long
        # this finally block isn't run and the alert gets stuck with is_calculating = True
        # hence when checking is_calculating, we also need to check if task has been stuck in is_calculating for too long

        # Get all updates with alert checks
        alert.refresh_from_db()
        alert.is_calculating = False
        alert.save()


@transaction.atomic
def check_alert_and_notify_atomically(alert: AlertConfiguration, capture_ph_event: Callable) -> None:
    """
    Computes insight results, checks alert for breaches and notifies user.
    Only commits updates to alert state if all of the above complete successfully.
    TODO: Later separate notification mechanism from alert checking mechanism (when we move to CDP)
        so we can retry notification without re-computing insight.
    """
    tag_queries(alert_config_id=str(alert.id))
    user = cast(User, alert.created_by)

    # Event to count alert checks
    capture_ph_event(
        distinct_id=user.distinct_id,
        event="alert check",
        properties={
            "alert_id": alert.id,
            "calculation_interval": alert.calculation_interval,
        },
    )

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
        error_message = f"Alert id = {alert.id}, failed to evaluate"

        capture_ph_event(
            distinct_id=user.distinct_id,
            event="alert check failed",
            properties={
                "alert_id": alert.id,
                "error": error_message,
                "traceback": traceback.format_exc(),
            },
        )

        logger.exception(error_message, exc_info=err)
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
                logger.info("Sending alert error notifications", alert_id=alert.id, error=alert_check.error)
                send_notifications_for_errors(alert, alert_check.error)
            case AlertState.FIRING:
                assert breaches is not None
                send_notifications_for_breaches(alert, breaches)
    except Exception as err:
        error_message = f"AlertCheckError: error sending notifications for alert_id = {alert.id}"
        logger.exception(error_message, exc_info=err)
        capture_exception(Exception(error_message))

        # don't want alert state to be updated (so that it's retried as next_check_at won't be updated)
        # so we raise again as @transaction.atomic decorator won't commit db updates
        # TODO: later should have a way just to retry notification mechanism
        raise


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """
    Matches insight type with alert checking logic
    """
    insight = alert.insight

    with upgrade_query(insight):
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
    alert.next_check_at = next_check_time(alert)

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
