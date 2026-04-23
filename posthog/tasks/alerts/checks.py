import traceback
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import cast

from django.db import transaction
from django.db.models import F, Q

import structlog
from celery import shared_task
from celery.canvas import chain
from dateutil.relativedelta import relativedelta
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.schema import AlertCalculationInterval, AlertState, TrendsQuery

from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions_capture import capture_exception
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.ph_client import ph_scoped_capture
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.tasks.alerts.detector import check_trends_alert_with_detector
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked, next_unblocked_utc
from posthog.tasks.alerts.trends import check_trends_alert
from posthog.tasks.alerts.utils import (
    WRAPPER_NODE_KINDS,
    AlertEvaluationResult,
    calculation_interval_to_order,
    disable_invalid_alert,
    dispatch_alert_notification,
    next_check_time,
    record_alert_delivery,
    skip_because_of_weekend,
    validate_alert_config,
)
from posthog.tasks.utils import CeleryQueue
from posthog.utils import get_from_dict_or_attr

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
        ),
        insight__deleted=False,
    ).count()

    now = datetime.now(UTC)

    daily_alerts_breaching_sla = AlertConfiguration.objects.filter(
        Q(
            enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
            last_checked_at__lte=now - relativedelta(days=1, minutes=15),
        ),
        insight__deleted=False,
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
        ),
        insight__deleted=False,
    )

    for alert in stuck_alerts:
        # we need to check the alert, reset is_calculating
        logger.info("check_alert.reset_stuck_alert", alert_id=alert.id)
        alert.is_calculating = False
        alert.save()


@shared_task(
    ignore_result=True,
    expires=60 * 60,
)
def investigation_notification_safety_net_task() -> None:
    """Force-dispatch notifications for gated alerts whose investigation stalled.

    Wraps posthog.tasks.alerts.investigation_notifications.run_investigation_notification_safety_net
    so it fits the existing Celery beat wiring.
    """
    from posthog.tasks.alerts.investigation_notifications import run_investigation_notification_safety_net

    try:
        run_investigation_notification_safety_net()
    except Exception as err:
        logger.exception("alert.investigation_safety_net_task_failed", exc_info=err)
        capture_exception(err)


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
        .filter(insight__deleted=False)
        .order_by(F("next_check_at").asc(nulls_first=True))
        .only("id", "team", "calculation_interval", "insight_id")
    )

    sorted_alerts = sorted(
        alerts,
        key=lambda alert: calculation_interval_to_order(
            cast(AlertCalculationInterval | None, alert.calculation_interval)
        ),
    )

    grouped_by_team: defaultdict[int, list[tuple[str, int, str | None, int]]] = defaultdict(list)
    for alert in sorted_alerts:
        grouped_by_team[alert.team_id].append(
            (
                str(alert.id),
                alert.team_id,
                cast(AlertCalculationInterval | None, alert.calculation_interval),
                alert.insight_id or 0,
            )
        )

    for alert_data in grouped_by_team.values():
        # We chain the task execution to prevent queries *for a single team* running at the same time
        chain(
            *(
                check_alert_task.si(alert_id, team_id, calculation_interval, insight_id).set(expires=expire_after)
                for alert_id, team_id, calculation_interval, insight_id in alert_data
            )
        )()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ALERTS.value,
    expires=60 * 60,
)
# @limit_concurrency(5)  Concurrency controlled by CeleryQueue.ALERTS for now
def check_alert_task(
    alert_id: str, team_id: int = 0, calculation_interval: str | None = None, insight_id: int = 0
) -> None:
    with ph_scoped_capture() as capture_ph_event:
        with slo_operation(
            spec=SloSpec(
                distinct_id=alert_id,
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ALERT_CHECK,
                team_id=team_id,
                resource_id=alert_id,
            ),
            properties={"calculation_interval": calculation_interval, "insight_id": insight_id},
            capture=capture_ph_event,
        ):
            check_alert(alert_id)


@retry(
    retry=retry_if_exception_type(CH_TRANSIENT_ERRORS),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=10),
    before_sleep=lambda rs: logger.info(
        "check_alert.retrying",
        attempt=rs.attempt_number,
        error=str(rs.outcome.exception()) if rs.outcome else None,
    ),
    reraise=True,
)
def check_alert(alert_id: str) -> None:
    try:
        alert = AlertConfiguration.objects.select_related("insight", "team").get(id=alert_id, enabled=True)
    except AlertConfiguration.DoesNotExist:
        logger.warning("Alert not found or not enabled", alert_id=alert_id)
        return

    if alert.insight.deleted:
        logger.info("Skipping alert for deleted insight", alert_id=alert_id, insight_id=alert.insight_id)
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
        alert.save(update_fields=["next_check_at"])
        return

    if is_utc_datetime_blocked(alert, now):
        logger.info(
            "Skipping alert check because of schedule restriction (quiet hours)",
            alert_id=alert.id,
        )
        alert.next_check_at = next_unblocked_utc(alert, now)
        alert.save(update_fields=["next_check_at"])
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

    try:
        insight = alert.insight
        with upgrade_query(insight):
            if insight.query is None:
                raise ValueError("Alert's insight has no valid query")
            threshold_config = alert.threshold.configuration if alert.threshold else None
            validate_alert_config(
                insight.query, alert.condition, alert.config, threshold_config, alert.calculation_interval
            )
    except ValueError as e:
        disable_invalid_alert(alert, str(e))
        return

    # we will attempt to check alert
    logger.info("check_alert", alert_id=alert.id)
    alert.last_checked_at = datetime.now(UTC)
    alert.is_calculating = True
    alert.save()

    try:
        check_alert_and_notify_atomically(alert)
    except Exception as err:
        logger.exception(AlertCheckException(err))
        capture_exception(
            AlertCheckException(err),
            additional_properties={
                "alert_configuration_id": alert_id,
                "insight_id": alert.insight_id,
                "team_id": alert.team_id,
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


INVESTIGATION_COOLDOWN = timedelta(hours=1)


@transaction.atomic
def check_alert_and_notify_atomically(alert: AlertConfiguration) -> None:
    """
    Computes insight results, checks alert for breaches and notifies user.
    Only commits updates to alert state if all of the above complete successfully.
    TODO: Later separate notification mechanism from alert checking mechanism (when we move to CDP)
        so we can retry notification without re-computing insight.
    """
    tag_queries(alert_config_id=str(alert.id))

    value = breaches = error = None
    alert_evaluation_result = None

    # Capture the prior state before add_alert_check mutates it, so we can detect
    # the NOT_FIRING/ERRORED -> FIRING transition and enqueue the investigation agent.
    previous_state = alert.state

    # 1. Evaluate insight and get alert value
    try:
        alert_evaluation_result = check_alert_for_insight(alert)
        value = alert_evaluation_result.value
        breaches = alert_evaluation_result.breaches
    except CH_TRANSIENT_ERRORS:
        # Re-raise so we retry the full flow
        raise
    except Exception as err:
        error_message = f"Alert id = {alert.id}, failed to evaluate"
        logger.exception(error_message, exc_info=err)
        capture_exception(AlertCheckException(err))

        # error can be on user side (incorrectly configured insight/alert)
        # we won't retry and set alert to errored state
        error = {"message": str(err), "traceback": traceback.format_exc()}

    # 2. Extract detector fields and create alert check
    anomaly_scores = getattr(alert_evaluation_result, "anomaly_scores", None) if alert_evaluation_result else None
    triggered_points = getattr(alert_evaluation_result, "triggered_points", None) if alert_evaluation_result else None
    triggered_dates = getattr(alert_evaluation_result, "triggered_dates", None) if alert_evaluation_result else None
    interval = getattr(alert_evaluation_result, "interval", None) if alert_evaluation_result else None
    triggered_metadata = (
        getattr(alert_evaluation_result, "triggered_metadata", None) if alert_evaluation_result else None
    )
    alert_check, should_notify = add_alert_check(
        alert,
        value,
        breaches,
        error,
        anomaly_scores,
        triggered_points,
        triggered_dates,
        interval,
        triggered_metadata,
    )

    # 3. Notify users if needed
    if not should_notify:
        return

    try:
        if alert_check.state == AlertState.FIRING and _investigation_should_gate_notification(alert, previous_state):
            # Hold notification — the investigation workflow will dispatch it after
            # the verdict, or the safety-net task will force-fire if the investigation
            # stalls.
            logger.info(
                "alert.notification_gated_on_investigation",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
            )
        else:
            targets = dispatch_alert_notification(alert, alert_check, breaches)
            if targets is not None:
                record_alert_delivery(alert, alert_check, targets)
                # notification_sent_at is the check-level idempotency marker read by
                # the investigation safety-net and workflow dispatchers; set it in
                # lock-step with record_alert_delivery so gating semantics match
                # regardless of which path actually dispatched.
                AlertCheck.objects.filter(id=alert_check.id).update(notification_sent_at=datetime.now(UTC))
        if alert_check.state == AlertState.FIRING:
            _maybe_start_investigation_agent(alert, alert_check, previous_state)
    except Exception as err:
        error_message = f"AlertCheckError: error sending notifications for alert_id = {alert.id}"
        logger.exception(error_message, exc_info=err)
        capture_exception(Exception(error_message))

        # don't want alert state to be updated (so that it's retried as next_check_at won't be updated)
        # so we raise again as @transaction.atomic decorator won't commit db updates
        # TODO: later should have a way just to retry notification mechanism
        raise


def _investigation_should_gate_notification(alert: AlertConfiguration, previous_state: str) -> bool:
    """True when this fire should hold its notification until the agent verdict is in.

    Gating only kicks in when the same preconditions as enqueueing the investigation
    itself are met, so we never defer a notification for a fire that won't actually
    get investigated — otherwise the safety-net task would be the only code path that
    ever notifies, which defeats the point.
    """
    if not alert.investigation_gates_notifications:
        return False
    if not alert.investigation_agent_enabled:
        return False
    if not alert.detector_config:
        return False
    if previous_state == AlertState.FIRING:
        return False
    # If the cooldown would cause _maybe_start_investigation_agent to skip this fire,
    # don't gate — no workflow will run and the only notifier would be the safety-net,
    # adding up to INVESTIGATION_NOTIFY_GRACE_MINUTES of avoidable latency.
    from posthog.models.alert import AlertCheck, InvestigationStatus

    cooldown_since = datetime.now(UTC) - INVESTIGATION_COOLDOWN
    if AlertCheck.objects.filter(
        alert_configuration=alert,
        created_at__gte=cooldown_since,
        investigation_status__in=[InvestigationStatus.RUNNING, InvestigationStatus.DONE, InvestigationStatus.PENDING],
    ).exists():
        return False
    return True


def _maybe_start_investigation_agent(alert: AlertConfiguration, alert_check: AlertCheck, previous_state: str) -> None:
    """Schedule the anomaly investigation workflow when the alert transitions to FIRING.

    Preconditions:
      - Alert opted in via investigation_agent_enabled.
      - Detector-based alert (threshold alerts are out of scope).
      - State transitioned from not-firing/errored/snoozed to FIRING — we don't
        re-investigate an already-firing alert.
      - No investigation was already kicked off for this alert within the cooldown,
        to protect against flappy alerts.
    """
    from posthog.models.alert import InvestigationStatus

    if not alert.investigation_agent_enabled:
        return
    if not alert.detector_config:
        return
    if previous_state == AlertState.FIRING:
        return

    cooldown_since = datetime.now(UTC) - INVESTIGATION_COOLDOWN
    recent_investigations = AlertCheck.objects.filter(
        alert_configuration=alert,
        created_at__gte=cooldown_since,
        investigation_status__in=[
            InvestigationStatus.RUNNING,
            InvestigationStatus.DONE,
            InvestigationStatus.PENDING,
        ],
    ).exclude(id=alert_check.id)
    if recent_investigations.exists():
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return

    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)

    def _enqueue() -> None:
        try:
            _start_investigation_workflow(alert, alert_check)
        except Exception as err:
            logger.exception(
                "alert.investigation_workflow_enqueue_failed",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
            )
            AlertCheck.objects.filter(id=alert_check.id).update(
                investigation_status=InvestigationStatus.FAILED,
                investigation_error={"message": f"Failed to enqueue workflow: {err}"},
            )

    # Enqueue outside the atomic transaction — we don't want a transient temporal
    # client hiccup to roll back the notification state.
    transaction.on_commit(_enqueue)


def _start_investigation_workflow(alert: AlertConfiguration, alert_check: AlertCheck) -> None:
    import asyncio

    from django.conf import settings

    from posthog.temporal.ai.anomaly_investigation import AnomalyInvestigationWorkflowInputs
    from posthog.temporal.common.client import sync_connect

    client = sync_connect()
    inputs = AnomalyInvestigationWorkflowInputs(
        team_id=alert.team_id,
        alert_id=alert.id,
        alert_check_id=alert_check.id,
        user_id=alert.created_by_id,
    )
    asyncio.run(
        client.start_workflow(
            "anomaly-investigation",
            inputs,
            id=f"anomaly-investigation-{alert_check.id}",
            task_queue=settings.MAX_AI_TASK_QUEUE,
        )
    )


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """
    Matches insight type with alert checking logic.

    If detector_config is set, uses the detector abstraction.
    Otherwise falls back to threshold-based checking.
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
                # Use detector-based checking if detector_config is set
                if alert.detector_config:
                    return check_trends_alert_with_detector(alert, insight, query, alert.detector_config)
                return check_trends_alert(alert, insight, query)
            case _:
                raise NotImplementedError(f"AlertCheckError: Alerts for {kind} are not supported yet")


def add_alert_check(
    alert: AlertConfiguration,
    value: float | None,
    breaches: list[str] | None,
    error: dict | None,
    anomaly_scores: list[float | None] | None = None,
    triggered_points: list[int] | None = None,
    triggered_dates: list[str] | None = None,
    interval: str | None = None,
    triggered_metadata: dict | None = None,
) -> tuple[AlertCheck, bool]:
    """Persist an AlertCheck row and return it plus a decision on whether notification is needed.

    `targets_notified` is always created empty; `notify_alert_activity` fills it on
    successful delivery and treats a non-empty value as the idempotency sentinel on retry.
    `last_notified_at` is likewise set by the notify activity on success, not here.
    """
    should_notify = False

    if error:
        alert.state = AlertState.ERRORED
        should_notify = True
    elif breaches:
        alert.state = AlertState.FIRING
        should_notify = True
    else:
        alert.state = AlertState.NOT_FIRING  # Set the Alert to not firing if the threshold is no longer met
        # TODO: Optionally send a resolved notification when alert goes from firing to not_firing?

    alert.last_checked_at = datetime.now(UTC)

    # IMPORTANT: update next_check_at according to interval
    # ensure we don't recheck alert until the next interval is due
    alert.next_check_at = next_check_time(alert)

    alert_check = AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=value,
        condition=alert.condition,
        targets_notified={},
        state=alert.state,
        triggered_metadata=triggered_metadata,
        error=error,
        anomaly_scores=anomaly_scores,
        triggered_points=triggered_points,
        triggered_dates=triggered_dates,
        interval=interval,
    )

    alert.save(update_fields=["state", "last_checked_at", "next_check_at"])

    return alert_check, should_notify
