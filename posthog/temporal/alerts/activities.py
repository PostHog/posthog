import traceback
from datetime import UTC, datetime

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.schema import AlertCalculationInterval, AlertState

from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions_capture import capture_exception
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.sync import database_sync_to_async
from posthog.tasks.alerts.checks import AlertCheckException, add_alert_check, check_alert_for_insight
from posthog.tasks.alerts.investigation_notifications import run_investigation_notification_safety_net
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked, next_unblocked_utc
from posthog.tasks.alerts.utils import (
    disable_invalid_alert,
    dispatch_alert_notification,
    next_check_time,
    record_alert_delivery,
    skip_because_of_weekend,
    validate_alert_config,
)
from posthog.temporal.alerts.investigation import claim_investigation_slot, should_trigger_investigation
from posthog.temporal.alerts.types import (
    AlertInfo,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
    SkipReason,
)
from posthog.temporal.common.heartbeat import Heartbeater

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def retrieve_due_alerts() -> list[AlertInfo]:
    @database_sync_to_async(thread_sensitive=False)
    def get_alerts() -> list[AlertInfo]:
        now = datetime.now(UTC)

        # Hourly before daily before weekly/monthly so the cheaper, more
        # time-sensitive checks get workers first when the due batch is large.
        calculation_interval_order = Case(
            When(calculation_interval=AlertCalculationInterval.HOURLY.value, then=Value(0)),
            When(calculation_interval=AlertCalculationInterval.DAILY.value, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )

        alerts = (
            AlertConfiguration.objects.filter(
                Q(enabled=True, next_check_at__lte=now) | Q(enabled=True, next_check_at__isnull=True)
            )
            .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
            .filter(insight__deleted=False)
            .annotate(_interval_order=calculation_interval_order)
            .order_by("_interval_order", F("next_check_at").asc(nulls_first=True))
            .only("id", "team_id", "calculation_interval", "insight_id")
        )

        return [
            AlertInfo(
                alert_id=str(a.id),
                team_id=a.team_id,
                distinct_id=str(a.id),
                calculation_interval=a.calculation_interval,
                insight_id=a.insight_id,
            )
            for a in alerts
        ]

    async with Heartbeater():
        return await get_alerts()


@temporalio.activity.defn
async def prepare_alert(inputs: PrepareAlertActivityInputs) -> PrepareAlertResult:
    """Load the alert, validate its config, and decide whether to evaluate."""

    @database_sync_to_async(thread_sensitive=False)
    def _prepare() -> PrepareAlertResult:
        try:
            alert = AlertConfiguration.objects.select_related("insight", "team", "threshold").get(id=inputs.alert_id)
        except AlertConfiguration.DoesNotExist:
            logger.warning("Alert not found", alert_id=inputs.alert_id)
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.NOT_FOUND)

        if not alert.enabled:
            logger.info("Skipping disabled alert", alert_id=inputs.alert_id)
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.DISABLED)

        if alert.insight.deleted:
            logger.info(
                "Skipping alert for deleted insight",
                alert_id=inputs.alert_id,
                insight_id=alert.insight_id,
            )
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.INSIGHT_DELETED)

        now = datetime.now(UTC)

        if alert.next_check_at and alert.next_check_at > now:
            logger.info(
                "Alert took too long to compute or was queued too long during which it already got "
                "computed. So not attempting to compute it again until it's due next",
                alert=alert,
            )
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.NOT_DUE)

        if skip_because_of_weekend(alert):
            logger.info("Skipping alert check because weekend checking is disabled", alert=alert)
            alert.next_check_at = next_check_time(alert)
            alert.save(update_fields=["next_check_at"])
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.WEEKEND)

        if is_utc_datetime_blocked(alert, now):
            logger.info(
                "Skipping alert check because of schedule restriction (quiet hours)",
                alert_id=alert.id,
            )
            alert.next_check_at = next_unblocked_utc(alert, now)
            alert.save(update_fields=["next_check_at"])
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.QUIET_HOURS)

        if alert.snoozed_until:
            if alert.snoozed_until > now:
                logger.info("Alert has been snoozed so skipping checking it now", alert=alert)
                return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.SNOOZED)
            # Snooze expired — persist clear so evaluate_alert reads the fresh state.
            alert.snoozed_until = None
            alert.state = AlertState.NOT_FIRING
            alert.save(update_fields=["snoozed_until", "state"])

        try:
            insight = alert.insight
            with upgrade_query(insight):
                if insight.query is None:
                    raise ValueError("Alert's insight has no valid query")
                threshold_config = alert.threshold.configuration if alert.threshold else None
                validate_alert_config(
                    insight.query,
                    alert.condition,
                    alert.config,
                    threshold_config,
                    alert.calculation_interval,
                )
        except ValueError as e:
            disable_invalid_alert(alert, str(e))
            return PrepareAlertResult(action=PrepareAction.AUTO_DISABLE, reason=str(e))

        return PrepareAlertResult(action=PrepareAction.EVALUATE)

    async with Heartbeater():
        return await _prepare()


@temporalio.activity.defn
async def evaluate_alert(inputs: EvaluateAlertActivityInputs) -> EvaluateAlertResult:
    """Run the insight ClickHouse query, apply the state machine, persist an AlertCheck row."""

    @database_sync_to_async(thread_sensitive=False)
    def _evaluate() -> EvaluateAlertResult:
        # Guard against the race where the alert is disabled/deleted between prepare_alert and
        # evaluate_alert (e.g. user disables via API mid-workflow). Retries can't recover from
        # either case, so surface as non-retryable to avoid a retry storm.
        try:
            alert = AlertConfiguration.objects.select_related("insight", "team", "threshold").get(id=inputs.alert_id)
        except AlertConfiguration.DoesNotExist:
            raise ApplicationError(
                f"Alert {inputs.alert_id} not found between prepare and evaluate",
                non_retryable=True,
            )

        if not alert.enabled:
            raise ApplicationError(
                f"Alert {inputs.alert_id} disabled between prepare and evaluate",
                non_retryable=True,
            )

        # CH workload management keys off this tag to isolate alert queries from other tenants.
        tag_queries(alert_config_id=str(alert.id))

        # Snapshot before add_alert_check mutates alert.state — needed to detect the
        # NOT_FIRING/ERRORED -> FIRING transition that triggers an investigation.
        previous_state = alert.state

        value: float | None = None
        breaches: list[str] | None = None
        error: dict | None = None
        alert_evaluation_result = None

        try:
            alert_evaluation_result = check_alert_for_insight(alert)
            value = alert_evaluation_result.value
            breaches = alert_evaluation_result.breaches
        except CH_TRANSIENT_ERRORS:
            raise
        except Exception as err:
            logger.exception(f"Alert id = {alert.id}, failed to evaluate", exc_info=err)
            capture_exception(
                AlertCheckException(err),
                additional_properties={
                    "alert_configuration_id": str(alert.id),
                    "insight_id": alert.insight_id,
                    "team_id": alert.team_id,
                },
            )
            error = {"message": str(err), "traceback": traceback.format_exc()}

        anomaly_scores = alert_evaluation_result.anomaly_scores if alert_evaluation_result else None
        triggered_points = alert_evaluation_result.triggered_points if alert_evaluation_result else None
        triggered_dates = alert_evaluation_result.triggered_dates if alert_evaluation_result else None
        interval = alert_evaluation_result.interval if alert_evaluation_result else None
        triggered_metadata = alert_evaluation_result.triggered_metadata if alert_evaluation_result else None

        should_start_investigation = False
        should_gate_notification = False
        with transaction.atomic():
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

            if should_trigger_investigation(
                alert,
                previous_state=previous_state,
                new_state=alert_check.state,
            ):
                if claim_investigation_slot(alert, alert_check):
                    should_start_investigation = True
                    should_gate_notification = bool(alert.investigation_gates_notifications)

        return EvaluateAlertResult(
            alert_check_id=str(alert_check.id),
            should_notify=should_notify,
            new_state=AlertState(alert_check.state),
            breaches=breaches,
            should_start_investigation=should_start_investigation,
            should_gate_notification=should_gate_notification,
            investigation_user_id=alert.created_by_id if should_start_investigation else None,
        )

    async with Heartbeater():
        return await _evaluate()


def dispatch_alert_firing_realtime_notification(alert: AlertConfiguration, breaches: list[str]) -> None:
    """Fan out one realtime in-app notification per subscribed user when an alert fires.

    Exceptions are caught and logged internally so a realtime delivery failure does not
    poison the email path or the alert-check transaction.
    """
    try:
        body = "; ".join(breaches[:3])
        if len(breaches) > 3:
            body += f" (+{len(breaches) - 3} more)"
        title = f"Alert firing: {alert.name}"[:100]
        source_url = f"/project/{alert.team.project_id}/insights/{alert.insight.short_id}#alert={alert.id}"
        for user_id in alert.subscribed_users.values_list("id", flat=True):
            create_notification(
                NotificationData(
                    team_id=alert.team_id,
                    notification_type=NotificationType.ALERT_FIRING,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.USER,
                    target_id=str(user_id),
                    resource_type="insight",
                    resource_id=str(alert.insight.short_id),
                    source_url=source_url,
                    source_type=SourceType.INSIGHT,
                    source_id=str(alert.insight.short_id),
                )
            )
    except Exception:
        logger.exception("alerts.realtime_notification_failed", alert_id=str(alert.id))


# Idempotency: empty targets_notified = not yet delivered; non-empty = already delivered.
# Lets Temporal retry notify_alert safely after a transient failure past the send.
@temporalio.activity.defn
async def notify_alert(inputs: NotifyAlertActivityInputs) -> None:
    """Send notifications for a previously evaluated alert check (idempotent)."""

    @database_sync_to_async(thread_sensitive=False)
    def _notify() -> None:
        # Mismatched pair surfaces as DoesNotExist instead of notifying the wrong alert.
        alert_check = AlertCheck.objects.select_related("alert_configuration", "alert_configuration__team").get(
            pk=inputs.alert_check_id,
            alert_configuration_id=inputs.alert_id,
        )

        if alert_check.targets_notified:
            logger.info(
                "notify_alert: already notified, skipping",
                alert_id=inputs.alert_id,
                alert_check_id=alert_check.id,
            )
            return

        alert = alert_check.alert_configuration

        # Raises if FIRING with no breaches; caller (workflow) must pipe breaches from evaluate.
        targets = dispatch_alert_notification(alert, alert_check, inputs.breaches)
        if targets is None:
            return

        with transaction.atomic():
            record_alert_delivery(alert, alert_check, targets)
            # Stamp notification_sent_at in lock-step with delivery — the investigation
            # workflow and safety-net both read this column to decide whether they still
            # need to dispatch, and the gating path relies on it for idempotency.
            AlertCheck.objects.filter(id=alert_check.id).update(notification_sent_at=datetime.now(UTC))

        # Realtime in-app dispatch sits AFTER record_alert_delivery so a Temporal retry
        # past this point sees `targets_notified` populated and skips the whole _notify.
        if alert_check.state == AlertState.FIRING.value and inputs.breaches:
            dispatch_alert_firing_realtime_notification(alert, inputs.breaches)

    async with Heartbeater():
        await _notify()


@temporalio.activity.defn
async def run_investigation_safety_net() -> int:
    """Force-dispatch notifications for gated AlertChecks whose investigation stalled.

    Returns the number of checks that were force-notified (for metrics / tests).
    """

    @database_sync_to_async(thread_sensitive=False)
    def _sweep() -> int:
        return run_investigation_notification_safety_net()

    async with Heartbeater():
        return await _sweep()
