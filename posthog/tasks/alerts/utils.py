from dataclasses import dataclass
from datetime import UTC, datetime

from django.utils import timezone

import pytz
import structlog
from dateutil.relativedelta import relativedelta

from posthog.schema import AlertCalculationInterval, AlertState, ChartDisplayType, NodeKind, TrendsQuery

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.tasks.alerts.schedule_restriction import snap_candidate_utc_to_schedule_restriction

from products.alerts.backend.calendar import (
    EVERY_15_MINUTES_CADENCE_MINUTES as EVERY_15_MINUTES_CADENCE_MINUTES,
    REAL_TIME_CADENCE_MINUTES as REAL_TIME_CADENCE_MINUTES,
    calendar_interval_to_relativedelta,
    is_weekend,
    next_calendar_check_time,
    to_calendar_interval,
)
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, derive_detector_event_fields

logger = structlog.get_logger(__name__)


@dataclass
class AlertEvaluationResult:
    value: float | None
    breaches: list[str] | None
    anomaly_scores: list[float | None] | None = None
    triggered_points: list[int] | None = None
    triggered_dates: list[str] | None = None
    interval: str | None = None
    triggered_metadata: dict | None = None


WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

NON_TIME_SERIES_DISPLAY_TYPES = {
    ChartDisplayType.BOLD_NUMBER,
    ChartDisplayType.ACTIONS_PIE,
    ChartDisplayType.ACTIONS_BAR_VALUE,
    ChartDisplayType.ACTIONS_TABLE,
    ChartDisplayType.WORLD_MAP,
}


def is_non_time_series_trend(query: TrendsQuery) -> bool:
    display = query.trendsFilter.display if query.trendsFilter else None
    return display in NON_TIME_SERIES_DISPLAY_TYPES


# Cheaper, more time-sensitive checks get workers first when the due batch is large.
# Single source for both the Python ordering and the ORM Case in
# posthog/temporal/alerts/activities.py retrieve_due_alerts.
CALCULATION_INTERVAL_ORDER: dict[AlertCalculationInterval, int] = {
    AlertCalculationInterval.REAL_TIME: 0,
    AlertCalculationInterval.EVERY_15_MINUTES: 1,
    AlertCalculationInterval.HOURLY: 2,
    AlertCalculationInterval.DAILY: 3,
    AlertCalculationInterval.WEEKLY: 4,
    AlertCalculationInterval.MONTHLY: 4,
}


def calculation_interval_to_order(interval: AlertCalculationInterval | None) -> int:
    if interval is None:
        raise ValueError("Invalid alert calculation interval: None")
    try:
        return CALCULATION_INTERVAL_ORDER[interval]
    except KeyError:
        raise ValueError(f"Unhandled alert calculation interval: {interval!r}")


def alert_calculation_interval_to_relativedelta(alert_calculation_interval: AlertCalculationInterval) -> relativedelta:
    return calendar_interval_to_relativedelta(to_calendar_interval(alert_calculation_interval))


def skip_because_of_weekend(alert: AlertConfiguration) -> bool:
    if not alert.skip_weekend:
        return False
    return is_weekend(datetime.now(pytz.UTC), alert.team.timezone)


def _next_check_time_core(alert: AlertConfiguration) -> datetime:
    """Nominal next check instant before schedule_restriction snapping."""
    return next_calendar_check_time(
        to_calendar_interval(alert.calculation_interval),
        now=datetime.now(pytz.UTC),
        tz_name=alert.team.timezone,
        next_check_at=alert.next_check_at,
    )


def next_check_time(alert: AlertConfiguration) -> datetime:
    """
    Rule by calculation interval

    hourly alerts -> want them to run at the same min every hour (same min comes from creation time so that they're spread out and don't all run at the start of the hour)
    daily alerts -> want them to run at the start of the day (around 1am) by the timezone of the team
    weekly alerts -> want them to run at the start of the week (Mon around 3am) by the timezone of the team
    monthly alerts -> want them to run at the start of the month (first day of the month around 4am) by the timezone of the team
    """
    candidate = _next_check_time_core(alert)
    return snap_candidate_utc_to_schedule_restriction(alert, candidate)


def next_check_at_after_schedule_restriction_change(alert: AlertConfiguration) -> datetime:
    """
    After persisting a new schedule_restriction (or clearing it), compute next_check_at like
    ``mark_for_recheck`` + ``next_check_time`` (same as the worker after a check).

    We temporarily clear ``next_check_at`` so the interval math uses *now* (not a stale future instant).
    Otherwise a previously snapped time (e.g. first minute after quiet hours) can stick at 4pm local
    even when it is still morning and earlier hourly runs are allowed.
    """
    old_next = alert.next_check_at
    try:
        alert.next_check_at = None
        return next_check_time(alert)
    finally:
        alert.next_check_at = old_next


def trigger_alert_hog_functions(alert: AlertConfiguration, properties: dict) -> None:
    """Trigger all HogFunctions linked to the alert as notification destinations by producing an internal event."""

    logger.info(
        "Triggering internal event for alert destinations/hog functions",
        alert_id=alert.id,
        properties=properties,
    )

    try:
        props = {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "project_name": alert.team.name,
            "insight_name": alert.insight.name,
            "insight_id": alert.insight.short_id,
            "state": alert.state,
            "last_checked_at": alert.last_checked_at.isoformat() if alert.last_checked_at else None,
            **derive_detector_event_fields(alert.detector_config),
            **properties,
        }

        produce_internal_event(
            team_id=alert.team_id,
            event=InternalEventEvent(
                event="$insight_alert_firing",
                distinct_id=f"team_{alert.team_id}",
                properties=props,
            ),
        )

    except Exception as e:
        capture_exception(
            e,
            additional_properties={
                "alert_id": str(alert.id),
                "feature": "alerts",
            },
        )
        logger.error(
            "Failed to produce internal event for alert destinations/hog functions",
            alert_id=alert.id,
            error=str(e),
            exc_info=True,
        )


def send_notifications_for_breaches(
    alert: AlertConfiguration,
    breaches: list[str],
    idempotency_key: str,
    extra_properties: dict[str, str] | None = None,
) -> list[str]:
    """A stable idempotency_key (typically alert_check.id) lets MessagingRecord enforce
    per-recipient at-most-once delivery on retries.

    `extra_properties` are merged into the internal-event properties that HogFunction
    destinations render (e.g. the anomaly investigation notebook URL for the Slack button).
    """
    email_targets = alert.get_subscribed_users_emails()
    if email_targets:
        subject = f"PostHog alert {alert.name} is firing for {alert.team.name}"
        campaign_key = f"alert-firing-notification-{idempotency_key}"
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
                "project_name": alert.team.name,
            },
        )

        for target in email_targets:
            message.add_recipient(email=target)

        logger.info("send_notifications_for_breaches", alert_id=alert.id, anomaly_count=len(breaches))
        message.send()

    # Join with newlines so each breach/investigation line renders on its own line in
    # Slack/Discord/Teams destinations rather than as one run-on comma-separated string.
    trigger_alert_hog_functions(alert=alert, properties={"breaches": "\n".join(breaches), **(extra_properties or {})})

    return email_targets


def send_notifications_for_errors(alert: AlertConfiguration, error: dict) -> list[str]:
    logger.info("Sending alert error notifications", alert_id=alert.id, error=error)
    email_targets = alert.get_subscribed_users_emails()

    # TODO: uncomment this after checking errors sent
    # if email_targets:
    #     subject = f"PostHog alert {alert.name} check failed to evaluate"
    #     campaign_key = f"alert-firing-notification-{alert.id}-{timezone.now().timestamp()}"
    #     insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    #     alert_url = f"{insight_url}?alert_id={alert.id}"
    #     message = EmailMessage(
    #         campaign_key=campaign_key,
    #         subject=subject,
    #         template_name="alert_check_failed_to_evaluate",
    #         template_context={
    #             "alert_error": error,
    #             "insight_url": insight_url,
    #             "insight_name": alert.insight.name,
    #             "alert_url": alert_url,
    #             "alert_name": alert.name,
    #         },
    #     )
    #     for target in email_targets:
    #         message.add_recipient(email=target)
    #     message.send()

    return email_targets


def dispatch_alert_notification(
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    breaches: list[str] | None,
    extra_properties: dict[str, str] | None = None,
) -> list[str] | None:
    """Route an AlertCheck to the correct notification sender.

    Returns the list of recipients the delivery targeted, or None if nothing was sent
    (NOT_FIRING, or ERRORED with a non-dict error payload). Callers pass the returned
    list to record_alert_delivery so the `targets_notified` sentinel reflects reality
    — never claiming delivery for a state that didn't actually send.

    Raises:
        ValueError: state is FIRING but breaches is None/empty.
        AssertionError: unknown state — surfaces a missing AlertState branch loudly.
    """
    match alert_check.state:
        case AlertState.NOT_FIRING:
            logger.info("Check state is NOT_FIRING, nothing to send", alert_id=alert.id)
            return None
        case AlertState.ERRORED:
            if not isinstance(alert_check.error, dict):
                logger.warning(
                    "ERRORED alert_check has non-dict error payload; skipping notification",
                    alert_id=alert.id,
                    alert_check_id=alert_check.id,
                )
                return None
            return send_notifications_for_errors(alert, alert_check.error)
        case AlertState.FIRING:
            if not breaches:
                raise ValueError(
                    f"dispatch_alert_notification: FIRING alert_check {alert_check.id} has no breaches — "
                    "caller must pass the breaches list from AlertEvaluationResult"
                )
            logger.info("Sending alert firing notifications", alert_id=alert.id)
            # Only forward extra_properties when there's something to add (anomaly investigations),
            # keeping the common threshold-alert call unchanged.
            if extra_properties:
                return send_notifications_for_breaches(
                    alert, breaches, idempotency_key=str(alert_check.id), extra_properties=extra_properties
                )
            return send_notifications_for_breaches(alert, breaches, idempotency_key=str(alert_check.id))
        case _:
            raise AssertionError(f"dispatch_alert_notification: unhandled alert state: {alert_check.state}")


def record_alert_delivery(alert: AlertConfiguration, alert_check: AlertCheck, targets: list[str]) -> None:
    """Persist the side-effects of a successful notification delivery.

    - alert_check.targets_notified: populated set = delivery happened (idempotency sentinel
      for Temporal notify retries).
    - alert.last_notified_at: used by monitoring / throttling.

    Caller must wrap in transaction.atomic() if atomic semantics are required.
    """
    alert_check.targets_notified = {"users": targets}
    alert_check.save(update_fields=["targets_notified"])
    alert.last_notified_at = datetime.now(UTC)
    alert.save(update_fields=["last_notified_at"])


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

    ``targets_notified`` is always created empty; ``notify_alert`` activity fills it on
    successful delivery and treats a non-empty value as the idempotency sentinel on retry.
    ``last_notified_at`` is likewise set by the notify activity on success, not here.
    """
    notify = False

    if error:
        alert.state = AlertState.ERRORED
        notify = True
    elif breaches:
        alert.state = AlertState.FIRING
        notify = True
    else:
        alert.state = AlertState.NOT_FIRING  # Threshold no longer met

    alert.last_checked_at = datetime.now(UTC)
    # Update next_check_at per interval so we don't recheck until the next one is due.
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

    return alert_check, notify


def disable_invalid_alert(alert: AlertConfiguration, reason: str) -> AlertCheck:
    """Auto-disable a misconfigured alert and email its subscribers.

    Used for configuration problems that make the alert unevaluable as set up — a deliberate,
    fail-loud outcome, not a bug — so the reason is surfaced to the owner rather than captured
    as an exception. Returns the recorded ERRORED AlertCheck so callers can reference it.
    """
    logger.warning("check_alert.auto_disabling", alert_id=alert.id, reason=reason)
    AlertConfiguration.objects.filter(pk=alert.pk).update(
        enabled=False,
        state=AlertState.ERRORED,
        last_checked_at=datetime.now(UTC),
    )
    alert.refresh_from_db()

    targets_to_notify = alert.get_subscribed_users_emails()
    alert_check = AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=None,
        condition=alert.condition,
        targets_notified={"users": targets_to_notify} if targets_to_notify else {},
        state=AlertState.ERRORED,
        error={"message": reason},
    )
    if targets_to_notify:
        send_notifications_for_disabled(alert, reason, targets_to_notify)
    return alert_check


def send_notifications_for_disabled(alert: AlertConfiguration, reason: str, targets: list[str]) -> None:
    logger.info("Sending alert disabled notification", alert_id=alert.id, reason=reason)

    subject = f"PostHog alert {alert.name} for {alert.team.name} has been disabled"
    campaign_key = f"alert-disabled-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}?alert_id={alert.id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="alert_disabled",
        template_context={
            "alert_url": alert_url,
            "alert_name": alert.name,
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "alert_error": reason,
            "project_name": alert.team.name,
        },
    )
    for target in targets:
        message.add_recipient(email=target)

    message.send()
