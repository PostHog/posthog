from collections.abc import Collection
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

import pytz
import structlog

from posthog.schema import AlertCalculationInterval, AlertState, ChartDisplayType, NodeKind, TrendsQuery

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.ph_client import ph_background_capture
from posthog.slo.context import get_current_slo
from posthog.slo.types import SloOperation
from posthog.tasks.alerts.schedule_restriction import snap_candidate_utc_to_schedule_restriction

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.delivery_slo import alert_delivery_slo
from products.alerts.backend.destinations import (
    ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS,
    AlertDelivery,
    alert_internal_event_delivered,
    flush_alert_internal_events,
    list_active_alert_destinations,
    produce_alert_internal_event,
    serialize_deliveries,
)
from products.alerts.backend.facade.api import send_alert_email
from products.alerts.backend.insight_alert_state_machine import (
    apply_invalid_configuration,
    apply_outcome,
    evaluate_alert_check,
    should_notify,
)
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, derive_detector_event_fields
from products.alerts.backend.scheduling import (
    EVERY_15_MINUTES_CADENCE_MINUTES as EVERY_15_MINUTES_CADENCE_MINUTES,
    REAL_TIME_CADENCE_MINUTES as REAL_TIME_CADENCE_MINUTES,
    is_weekend,
    next_calendar_check_time,
    to_calendar_interval,
)
from products.exports.backend.facade import api as exports

logger = structlog.get_logger(__name__)

INSIGHT_ALERT_FIRING_EVENT = "$insight_alert_firing"

# TTL for the tokenized chart URL embedded in Slack. Slack fetches the image at delivery,
# but the URL must stay resolvable while people scroll back to the message; 30 days matches
# the delivery-URL TTL used for task chart artifacts (products/tasks living_artifacts).
_INSIGHT_CHART_URL_TTL = timedelta(days=30)

# The stored PNG outlives its delivery URL by one day so the URL can never point at a
# deleted asset; without an explicit TTL the format default keeps the PNG for six months.
_INSIGHT_CHART_ASSET_TTL = timedelta(days=31)


@frozen
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
    ChartDisplayType.ACTIONS_DONUT,
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
    Clearing ``next_check_at`` before ``next_check_time`` matches the worker after a check.

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


def trigger_alert_hog_functions(alert: AlertConfiguration, properties: dict) -> list[AlertDelivery]:
    """Trigger all HogFunctions linked to the alert as notification destinations by producing an internal event.

    Returns one receipt per destination that accepted the notification. An empty list also
    covers an alert with no destinations configured, so callers cannot use it to tell
    "there was nothing to send" apart from "sending failed".
    """

    log_properties = dict(properties)
    if "insight_chart_url" in log_properties:
        # The chart URL embeds a bearer token, so logs must not carry a usable credential.
        log_properties["insight_chart_url"] = "[redacted]"
    logger.info(
        "Triggering internal event for alert destinations/hog functions",
        alert_id=alert.id,
        properties=log_properties,
    )

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

    destinations = list_active_alert_destinations(
        team_id=alert.team_id,
        alert_id=str(alert.id),
        allowed_event_ids=(INSIGHT_ALERT_FIRING_EVENT,),
    )
    accepted_at = datetime.now(UTC).isoformat()
    receipts = [
        AlertDelivery(
            channel="hog_function",
            target=destination.name,
            target_id=destination.id,
            template=destination.destination_type,
            at=accepted_at,
        )
        for destination in destinations
    ]

    produce_result = produce_alert_internal_event(
        team_id=alert.team_id,
        event_name=INSIGHT_ALERT_FIRING_EVENT,
        properties=props,
    )

    slo = get_current_slo()
    if slo is None or slo.operation != SloOperation.ALERT_DELIVERY:
        return receipts if produce_result is not None else []
    if produce_result is None:
        slo.fail(failure_phase="destination_enqueue")
        return []

    flush_alert_internal_events(ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS)
    if not alert_internal_event_delivered(
        produce_result,
        team_id=alert.team_id,
        alert_id=str(alert.id),
        event_name=INSIGHT_ALERT_FIRING_EVENT,
    ):
        slo.fail(failure_phase="notification_delivery")
        return []
    return receipts


def send_notifications_for_breaches(
    alert: AlertConfiguration,
    breaches: list[str],
    idempotency_key: str,
    extra_properties: dict[str, str] | None = None,
) -> list[AlertDelivery]:
    """A stable idempotency_key (typically alert_check.id) lets MessagingRecord enforce
    per-recipient at-most-once email delivery on retries.

    `extra_properties` are merged into the internal-event properties that HogFunction
    destinations render (e.g. the anomaly investigation notebook URL for the Slack button).
    """
    deliveries: list[AlertDelivery] = []
    email_targets = alert.get_subscribed_users_emails()
    if email_targets:
        subject = f"PostHog alert {alert.name} is firing for {alert.team.name}"
        campaign_key = f"alert-firing-notification-{idempotency_key}"
        insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
        alert_url = f"{insight_url}?alert_id={alert.id}"
        logger.info("send_notifications_for_breaches", alert_id=alert.id, anomaly_count=len(breaches))
        send_alert_email(
            recipients=email_targets,
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
        accepted_at = datetime.now(UTC).isoformat()
        deliveries.extend(AlertDelivery(channel="email", target=target, at=accepted_at) for target in email_targets)

    # Join with newlines so each breach/investigation line renders on its own line in
    # Slack/Discord/Teams destinations rather than as one run-on comma-separated string.
    deliveries.extend(
        trigger_alert_hog_functions(
            alert=alert,
            properties={"breaches": "\n".join(breaches), **(extra_properties or {})},
        )
    )

    return deliveries


def send_test_alert_email(alert: AlertConfiguration, recipients: Collection[str], idempotency_key: str) -> None:
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    send_alert_email(
        recipients=recipients,
        campaign_key=f"alert-test-notification-{idempotency_key}",
        subject=f"Test alert: {alert.name} for {alert.team.name}",
        template_name="alert_check_firing",
        template_context={
            "match_descriptions": ["This is a test alert. No action is needed."],
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "alert_url": f"{insight_url}?alert_id={alert.id}",
            "alert_name": alert.name,
            "project_name": alert.team.name,
            "is_test": True,
        },
    )


def send_notifications_for_errors(alert: AlertConfiguration, error: dict, idempotency_key: str) -> list[AlertDelivery]:
    logger.info("Sending alert error notifications", alert_id=alert.id, error=error)
    email_targets = [email for _, email in get_alert_error_notification_recipients(alert) if email]
    if not email_targets:
        return []

    alert_name = alert.name or "Your alert"
    subject_alert_name = alert.name or "your alert"
    error_message = str(error.get("message") or "Unknown error").strip()[:1000] or "Unknown error"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}?alert_id={alert.id}"
    send_alert_email(
        recipients=email_targets,
        campaign_key=f"alert-evaluation-failed-notification-{idempotency_key}",
        subject=f"PostHog could not evaluate {subject_alert_name}",
        template_name="alert_check_failed_to_evaluate",
        template_context={
            "alert_error": error_message,
            "alert_url": alert_url,
            "alert_name": alert_name,
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "next_check_at": alert.next_check_at,
        },
    )
    accepted_at = datetime.now(UTC).isoformat()
    return [AlertDelivery(channel="email", target=target, at=accepted_at) for target in email_targets]


def next_scheduled_check_time(alert: AlertConfiguration) -> str | None:
    if alert.next_check_at is None:
        return None
    return alert.next_check_at.astimezone(ZoneInfo(alert.team.timezone)).strftime("%B %-d, %Y at %-I:%M %p %Z")


def get_alert_error_notification_recipients(alert: AlertConfiguration) -> list[tuple[int, str]]:
    candidates = (
        alert.team.all_users_with_access()
        .filter(id__in=alert.subscribed_users.values_list("id", flat=True))
        .only("id", "email")
    )
    return [
        (user.id, user.email)
        for user in candidates
        if UserAccessControl(user, team=alert.team).check_access_level_for_object(alert.insight, "viewer")
    ]


def _inconclusive_is_suppressed(verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether an inconclusive verdict is held back by the alert's configured policy."""
    return verdict == "inconclusive" and (inconclusive_action or "notify") == "suppress"


def _should_suppress_notification(verdict: str | None, inconclusive_action: str | None) -> bool:
    """Whether the verdict holds the notification back: false positives always suppress,
    inconclusive follows the alert's configured policy."""
    return verdict == "false_positive" or _inconclusive_is_suppressed(verdict, inconclusive_action)


def _resolve_alert_render_user(alert: AlertConfiguration) -> User | None:
    """Pick the user the chart render is attributed to: the alert creator, then any
    subscribed user, then None. The render checks this user's view access to the insight,
    so it mirrors who the alert was set up for."""
    if alert.created_by_id:
        try:
            return User.objects.get(id=alert.created_by_id)
        except User.DoesNotExist:
            pass
    return alert.subscribed_users.first()


def prepare_alert_insight_chart_url(
    *,
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    user: User | None = None,
    verdict: str | None = None,
) -> str | None:
    """Render the alerted insight to a PNG and mint a URL Slack can embed as an image block.

    Skipped when nothing would show it: a suppressed verdict, an already-delivered check
    (a chart added after delivery would never reach the sent message), or no active Slack
    destination (only the Slack template renders the chart). Best-effort: on any failure
    (render error, no viewer access for the render user, export infrastructure down) return
    None so the notification still goes out, just without the chart.

    `user` attributes the render and is checked for view access; when omitted it falls back
    to the alert creator or a subscribed user. Pass it explicitly from a path that already
    resolved the acting user.
    """
    if _should_suppress_notification(verdict, alert.investigation_inconclusive_action):
        return None
    render_user = user or _resolve_alert_render_user(alert)
    if render_user is None:
        return None
    pending = AlertCheck.objects.filter(
        id=alert_check.id, notification_sent_at__isnull=True, notification_suppressed_by_agent=False
    ).exists()
    if not pending:
        return None
    try:
        destinations = list_active_alert_destinations(
            team_id=alert.team_id, alert_id=str(alert.id), allowed_event_ids=(INSIGHT_ALERT_FIRING_EVENT,)
        )
        if not any(destination.destination_type == "slack" for destination in destinations):
            return None
        asset, content = exports.render_png_export(
            team=alert.team,
            created_by=render_user,
            insight_id=alert.insight_id,
            # System render: keep it out of the user's export listings and quota.
            is_system=True,
            expires_after=datetime.now(UTC) + _INSIGHT_CHART_ASSET_TTL,
        )
        if content is None:
            logger.info(
                "alerts.insight_chart_render_failed",
                alert_id=str(alert.id),
                asset_id=asset.id,
                exception=asset.exception,
            )
            return None
        return exports.get_delivery_image_url(
            team_id=alert.team_id, asset_id=asset.id, expiry_delta=_INSIGHT_CHART_URL_TTL
        )
    except Exception:
        logger.exception("alerts.insight_chart_render_failed", alert_id=str(alert.id))
        return None


def dispatch_alert_notification(
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    breaches: list[str] | None,
    extra_properties: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    render_chart: bool = True,
) -> list[AlertDelivery] | None:
    """Route an AlertCheck to the correct notification sender.

    Returns the delivery receipts the notification produced, or None if nothing was sent
    (NOT_FIRING, or ERRORED with a non-dict error payload). Callers pass the returned
    receipts to record_alert_delivery so the `targets_notified` sentinel reflects reality,
    never claiming delivery for a state that didn't actually send.

    `idempotency_key` defaults to the check id, which gives at-most-once email delivery per
    check. A caller that deliberately sends a second message about the same check must pass
    its own key, or MessagingRecord drops that email as a duplicate of the first.

    `render_chart` controls the Slack chart render for a FIRING check. Pass False from a
    caller that holds an open transaction or a row lock: the render blocks for up to
    exports.RENDER_TIMEOUT, and waiting that long under a lock stalls every other
    dispatcher of the same check. Such a caller renders with
    prepare_alert_insight_chart_url before it opens the transaction, then passes the URL
    through `extra_properties`.

    Raises:
        ValueError: state is FIRING but breaches is None/empty.
        AssertionError: unknown state — surfaces a missing AlertState branch loudly.
    """
    key = idempotency_key or str(alert_check.id)
    with ExitStack() as stack:
        if alert_check.state == AlertState.FIRING:
            stack.enter_context(
                alert_delivery_slo(
                    alert_type="insight",
                    notification_action="fire",
                    distinct_id=str(alert.id),
                    team_id=alert.team_id,
                    resource_id=str(alert.id),
                    properties={
                        "alert_check_id": str(alert_check.id),
                        "alert_state": alert_check.state,
                        "calculation_interval": alert.calculation_interval,
                        "insight_id": alert.insight_id,
                    },
                )
            )

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
                return send_notifications_for_errors(alert, alert_check.error, idempotency_key=key)
            case AlertState.FIRING:
                if not breaches:
                    raise ValueError(
                        f"dispatch_alert_notification: FIRING alert_check {alert_check.id} has no breaches — "
                        "caller must pass the breaches list from AlertEvaluationResult"
                    )
                logger.info("Sending alert firing notifications", alert_id=alert.id)
                properties = dict(extra_properties) if extra_properties else {}
                # Attach the chart for any firing alert whose caller did not already supply
                # one, so ordinary threshold and anomaly alerts get the chart too, not just
                # the anomaly investigation path (which renders it early and passes it in).
                # Real-time alerts never render here: the render is capped at
                # exports.RENDER_TIMEOUT (90s), which outlasts the 60s notify_start_to_close
                # of _REAL_TIME_TIMEOUTS, so a slow render would time out the whole notify
                # activity and lose the notification it was supposed to carry.
                if (
                    render_chart
                    and "insight_chart_url" not in properties
                    and alert.calculation_interval != AlertCalculationInterval.REAL_TIME
                ):
                    chart_url = prepare_alert_insight_chart_url(alert=alert, alert_check=alert_check)
                    if chart_url:
                        properties["insight_chart_url"] = chart_url
                # Only forward extra_properties when there's something to add, keeping the
                # common threshold-alert call unchanged when nothing was attached.
                if properties:
                    return send_notifications_for_breaches(
                        alert, breaches, idempotency_key=key, extra_properties=properties
                    )
                return send_notifications_for_breaches(alert, breaches, idempotency_key=key)
            case _:
                raise AssertionError(f"dispatch_alert_notification: unhandled alert state: {alert_check.state}")


def record_alert_delivery(
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    deliveries: list[AlertDelivery] | None,
    *,
    stamp_on_empty: bool = False,
) -> bool:
    """Persist the side-effects of accepted notification deliveries.

    Returns False without recording anything when nothing was accepted, so a check
    can never claim delivery that didn't happen. `stamp_on_empty` is for the
    investigation-gated dispatchers: a zero-accept attempt must still stamp
    notification_sent_at (their sweep-idempotency marker), or the safety net would
    re-dispatch an undeliverable check forever.

    Caller must wrap in transaction.atomic() if atomic semantics are required.
    """
    if not deliveries:
        logger.warning(
            "record_alert_delivery.no_transport_accepted",
            alert_id=str(alert.id),
            alert_check_id=str(alert_check.id),
            alert_check_state=alert_check.state,
        )
        ph_background_capture()(
            distinct_id=str(alert.id),
            event="alert notification not delivered",
            properties={
                "team_id": alert.team_id,
                "alert_id": str(alert.id),
                "alert_check_id": str(alert_check.id),
                "alert_state": alert_check.state,
            },
        )
        if stamp_on_empty:
            alert_check.notification_sent_at = datetime.now(UTC)
            alert_check.save(update_fields=["notification_sent_at"])
        return False
    recorded_at = datetime.now(UTC)
    alert_check.targets_notified = {
        "users": [delivery.target for delivery in deliveries if delivery.channel == "email"],
        "destinations": serialize_deliveries([d for d in deliveries if d.channel != "email"]),
    }
    alert_check.notification_sent_at = recorded_at
    alert_check.save(update_fields=["targets_notified", "notification_sent_at"])
    alert.last_notified_at = recorded_at
    alert.save(update_fields=["last_notified_at"])
    return True


def add_alert_check(
    alert: AlertConfiguration,
    evaluation_result: AlertEvaluationResult | None,
    error: dict | None,
) -> tuple[AlertCheck, bool]:
    """Persist an AlertCheck row and return it plus a decision on whether notification is needed.

    ``targets_notified`` is always created empty; ``notify_alert`` activity fills it on
    successful delivery and treats a non-empty value as the idempotency sentinel on retry.
    ``last_notified_at`` is likewise set by the notify activity on success, not here.
    """
    # Evaluation never ran (query error): record an all-empty result so the check row still lands.
    result = evaluation_result if evaluation_result is not None else AlertEvaluationResult(value=None, breaches=None)
    error_message = error.get("message") if error else None
    outcome = evaluate_alert_check(
        alert,
        threshold_breached=bool(result.breaches),
        error_message=error_message,
        now=datetime.now(UTC),
    )
    state_fields = apply_outcome(alert, outcome)

    alert.last_checked_at = datetime.now(UTC)
    # Update next_check_at per interval so we don't recheck until the next one is due.
    alert.next_check_at = next_check_time(alert)

    alert_check = AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=result.value,
        condition=alert.condition,
        targets_notified={},
        state=alert.state,
        triggered_metadata=result.triggered_metadata,
        error=error,
        anomaly_scores=result.anomaly_scores,
        triggered_points=result.triggered_points,
        triggered_dates=result.triggered_dates,
        interval=result.interval,
    )

    alert.save(update_fields=[*state_fields, "last_checked_at", "next_check_at"])

    return alert_check, should_notify(outcome)


def disable_invalid_alert(
    alert: AlertConfiguration,
    reason: str,
    *,
    notify_subscribers: bool = True,
    error_code: str | None = None,
) -> AlertCheck:
    """Auto-disable a misconfigured alert and email its subscribers.

    Used for configuration problems that make the alert unevaluable as set up — a deliberate,
    fail-loud outcome, not a bug — so the reason is surfaced to the owner rather than captured
    as an exception. Returns the recorded ERRORED AlertCheck so callers can reference it.
    """
    logger.warning("check_alert.auto_disabling", alert_id=alert.id, reason=reason)
    state_fields = apply_invalid_configuration(alert)
    alert.last_checked_at = datetime.now(UTC)
    alert.save(update_fields=[*state_fields, "last_checked_at"])

    targets_to_notify = alert.get_subscribed_users_emails()
    error = {"message": reason}
    if error_code:
        error["code"] = error_code
    alert_check = AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=None,
        condition=alert.condition,
        targets_notified={},
        state=AlertState.ERRORED,
        error=error,
    )
    if targets_to_notify and notify_subscribers:
        deliveries = send_notifications_for_disabled(alert, reason, targets_to_notify)
        record_alert_delivery(alert, alert_check, deliveries)
    return alert_check


def send_notifications_for_disabled(alert: AlertConfiguration, reason: str, targets: list[str]) -> list[AlertDelivery]:
    logger.info("Sending alert disabled notification", alert_id=alert.id, reason=reason)

    subject = f"PostHog alert {alert.name} for {alert.team.name} has been disabled"
    campaign_key = f"alert-disabled-notification-{alert.id}-{timezone.now().timestamp()}"
    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}?alert_id={alert.id}"
    send_alert_email(
        recipients=targets,
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
    accepted_at = datetime.now(UTC).isoformat()
    return [AlertDelivery(channel="email", target=target, at=accepted_at) for target in targets]
