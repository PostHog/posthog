import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.utils import timezone

import pytz
import structlog
from dateutil.relativedelta import MO, relativedelta

from posthog.schema import (
    AlertCalculationInterval,
    AlertCondition,
    AlertConditionType,
    AlertState,
    ChartDisplayType,
    InsightThreshold,
    InsightThresholdType,
    NodeKind,
    TrendsAlertConfig,
    TrendsQuery,
)

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.email import EmailMessage
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.schedule_restriction import snap_candidate_utc_to_schedule_restriction
from posthog.tasks.exporter import export_asset_direct
from posthog.utils import get_from_dict_or_attr

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, derive_detector_event_fields
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType
from products.exports.backend.models.exported_asset import ExportedAsset

logger = structlog.get_logger(__name__)

# Internal event that alert HogFunction destinations (Slack, webhook, …) subscribe to.
INSIGHT_ALERT_FIRING_EVENT = "$insight_alert_firing"
# Event property the Slack template reads to render the chart image.
CHART_IMAGE_URL_PROPERTY = "chart_image_url"
# Short-lived so the bearer URL carried in the event isn't a long-lived credential. Slack proxies
# and caches the image on first fetch, so a few days comfortably covers display.
ALERT_CHART_IMAGE_URL_TTL = timedelta(days=7)


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


def validate_alert_config(
    query: dict,
    condition: dict | None,
    config: dict | None,
    threshold_config: dict | None = None,
    calculation_interval: str | None = None,
) -> None:
    """Validate alert configuration dicts. Raises ValueError on failure."""
    if not calculation_interval or not isinstance(calculation_interval, str):
        raise ValueError(f"Invalid calculation interval: {calculation_interval}")
    try:
        AlertCalculationInterval(calculation_interval)
    except ValueError:
        raise ValueError(f"Invalid calculation interval: {calculation_interval}")

    try:
        parsed_condition = AlertCondition.model_validate(condition)
    except Exception:
        raise ValueError(f"Alert has invalid condition: {condition}")

    if not config or not isinstance(config, dict) or config.get("type") != "TrendsAlertConfig":
        raise ValueError(f"Unsupported alert config type: {config}")
    try:
        parsed_config = TrendsAlertConfig.model_validate(config)
    except Exception:
        raise ValueError(f"Alert has invalid TrendsAlertConfig: {config}")

    kind = get_from_dict_or_attr(query, "kind")
    if kind in WRAPPER_NODE_KINDS:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    if kind != NodeKind.TRENDS_QUERY:
        raise ValueError(f"Alert's insight query kind '{kind}' is not supported (only TrendsQuery)")

    try:
        trends_query = TrendsQuery.model_validate(query)
    except Exception as e:
        raise ValueError(f"Alert's insight has an invalid TrendsQuery: {e}")

    if parsed_condition.type in (
        AlertConditionType.RELATIVE_INCREASE,
        AlertConditionType.RELATIVE_DECREASE,
    ) and is_non_time_series_trend(trends_query):
        raise ValueError(
            f"Relative alert condition '{parsed_condition.type}' is not compatible with non time series trends"
        )

    formula_nodes = trends_query.trendsFilter.formulaNodes if trends_query.trendsFilter else None
    result_count = len(formula_nodes) if formula_nodes else len(trends_query.series)
    if parsed_config.series_index >= result_count:
        raise ValueError(f"series_index {parsed_config.series_index} is out of range (query has {result_count} series)")

    if threshold_config is not None:
        try:
            threshold = InsightThreshold.model_validate(threshold_config)
        except Exception:
            raise ValueError(f"Alert has invalid threshold configuration: {threshold_config}")

        if (
            parsed_condition.type == AlertConditionType.ABSOLUTE_VALUE
            and threshold.type != InsightThresholdType.ABSOLUTE
        ):
            raise ValueError(
                "Absolute value alerts require an absolute threshold, but a percentage threshold was configured"
            )

        if parsed_config.check_ongoing_interval and parsed_condition.type in (
            AlertConditionType.ABSOLUTE_VALUE,
            AlertConditionType.RELATIVE_INCREASE,
        ):
            if not threshold.bounds or threshold.bounds.upper is None:
                raise ValueError(
                    f"check_ongoing_interval is only supported for alert condition {parsed_condition.type} when upper threshold is specified"
                )


def calculation_interval_to_order(interval: AlertCalculationInterval | None) -> int:
    match interval:
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return 0
        case AlertCalculationInterval.HOURLY:
            return 1
        case AlertCalculationInterval.DAILY:
            return 2
        case AlertCalculationInterval.WEEKLY:
            return 3
        case AlertCalculationInterval.MONTHLY:
            return 3
        case None:
            raise ValueError("Invalid alert calculation interval: None")
        case _ as unreachable:
            raise ValueError(f"Unhandled alert calculation interval: {unreachable!r}")


def alert_calculation_interval_to_relativedelta(alert_calculation_interval: AlertCalculationInterval) -> relativedelta:
    match alert_calculation_interval:
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return relativedelta(minutes=15)
        case AlertCalculationInterval.HOURLY:
            return relativedelta(hours=1)
        case AlertCalculationInterval.DAILY:
            return relativedelta(days=1)
        case AlertCalculationInterval.WEEKLY:
            return relativedelta(weeks=1)
        case AlertCalculationInterval.MONTHLY:
            return relativedelta(months=1)
        case _ as unreachable:
            raise ValueError(f"Unhandled alert calculation interval: {unreachable!r}")


def skip_because_of_weekend(alert: AlertConfiguration) -> bool:
    if not alert.skip_weekend:
        return False

    now = datetime.now(pytz.UTC)
    team_timezone = pytz.timezone(alert.team.timezone)

    now_local = now.astimezone(team_timezone)
    return now_local.isoweekday() in [6, 7]


def _next_check_time_core(alert: AlertConfiguration) -> datetime:
    """Nominal next check instant before schedule_restriction snapping."""
    now = datetime.now(pytz.UTC)
    team_timezone = pytz.timezone(alert.team.timezone)

    match alert.calculation_interval:
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return (alert.next_check_at or now) + relativedelta(minutes=15)
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
        case _ as unreachable:
            raise ValueError(f"Unhandled alert calculation interval: {unreachable!r}")


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
        # chart_image_url is a signed bearer URL — keep it out of logs.
        properties={k: v for k, v in properties.items() if k != CHART_IMAGE_URL_PROPERTY},
    )

    try:
        props = {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
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
                event=INSIGHT_ALERT_FIRING_EVENT,
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


def _destination_targets_alert(filters: dict | None, alert_id: str) -> bool:
    """A Slack destination consumes this alert's chart if it has no ``alert_id`` filter (team-wide)
    or one that matches this alert. A filter bound to a *different* alert does not."""
    alert_id_values = [p.get("value") for p in (filters or {}).get("properties", []) if p.get("key") == "alert_id"]
    if not alert_id_values:
        return True
    return any(
        alert_id in [str(v) for v in value] if isinstance(value, list) else str(value) == alert_id
        for value in alert_id_values
    )


def _inputs_reference_chart_image(inputs: dict | None) -> bool:
    """Whether a destination's stored inputs actually template the chart URL. Destinations created
    before this feature (or otherwise not displaying the chart) don't, so we skip the render for
    them rather than producing an asset nothing will show."""
    return CHART_IMAGE_URL_PROPERTY in json.dumps(inputs or {})


def alert_has_slack_destination(alert: AlertConfiguration) -> bool:
    """Whether *this* alert has an enabled Slack destination that will actually display the chart.

    Gates the (heavy) browser screenshot so we only render when a Slack destination both targets
    this alert (or is team-wide) *and* references the chart image in its blocks. This skips
    destinations bound to a different alert and pre-existing destinations whose stored blocks don't
    yet template the chart URL. The candidate set per team is small, so these checks run in Python
    to sidestep JSONB null semantics for destinations without a ``properties`` filter.
    """
    candidates = HogFunction.objects.filter(
        team_id=alert.team_id,
        enabled=True,
        deleted=False,
        type=HogFunctionType.INTERNAL_DESTINATION,
        template_id="template-slack",
        filters__events__contains=[{"id": INSIGHT_ALERT_FIRING_EVENT}],
    ).values_list("filters", "inputs")
    return any(
        _destination_targets_alert(filters, str(alert.id)) and _inputs_reference_chart_image(inputs)
        for filters, inputs in candidates
    )


def generate_alert_chart_image_url(alert: AlertConfiguration) -> str | None:
    """Render the alert's insight to a PNG and return a signed delivery URL for Slack to embed.

    Best-effort: returns None only if we can't create the asset at all. The ExportedAsset (and
    therefore the URL) is created *before* the heavy browser render, so the URL is a valid,
    Slack-fetchable link even if the screenshot itself fails — Slack then shows an unloadable
    image rather than rejecting the whole message.
    """
    try:
        asset = ExportedAsset.objects.create(
            team=alert.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=alert.insight,
            created_by=alert.created_by,
            # System-generated: excluded from the per-team user-export quota.
            is_system=True,
            # Expire with the delivery URL rather than the default 6-month PNG retention — these
            # are single-use Slack assets and Slack caches the image on first fetch.
            expires_after=timezone.now() + ALERT_CHART_IMAGE_URL_TTL,
        )
    except Exception as e:
        capture_exception(e, additional_properties={"alert_id": str(alert.id), "feature": "alerts"})
        logger.exception("alerts.chart_image_asset_creation_failed", alert_id=str(alert.id))
        return None

    try:
        export_asset_direct(asset, source=EventSource.ALERT)
    except Exception as e:
        # Don't fail the notification over a render error — the URL is still valid, Slack just
        # won't be able to load the image.
        capture_exception(e, additional_properties={"alert_id": str(alert.id), "feature": "alerts"})
        logger.exception("alerts.chart_image_render_failed", alert_id=str(alert.id), asset_id=asset.id)

    return asset.get_subscription_delivery_content_url(expiry_delta=ALERT_CHART_IMAGE_URL_TTL)


def send_notifications_for_breaches(alert: AlertConfiguration, breaches: list[str], idempotency_key: str) -> list[str]:
    """A stable idempotency_key (typically alert_check.id) lets MessagingRecord enforce
    per-recipient at-most-once delivery on retries.
    """
    email_targets = alert.get_subscribed_users_emails()
    if email_targets:
        subject = f"PostHog alert {alert.name} is firing"
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
            },
        )

        for target in email_targets:
            message.add_recipient(email=target)

        logger.info("send_notifications_for_breaches", alert_id=alert.id, anomaly_count=len(breaches))
        message.send()

    hog_function_properties: dict = {"breaches": ", ".join(breaches)}
    # Only render when a Slack destination will actually display the chart — the screenshot is expensive.
    if alert_has_slack_destination(alert):
        chart_image_url = generate_alert_chart_image_url(alert)
        if chart_image_url:
            hog_function_properties[CHART_IMAGE_URL_PROPERTY] = chart_image_url

    trigger_alert_hog_functions(alert=alert, properties=hog_function_properties)

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


def check_alert_for_insight(alert: AlertConfiguration) -> AlertEvaluationResult:
    """Dispatch an alert to the correct insight-kind-specific evaluator.

    If ``detector_config`` is set, uses the detector abstraction; otherwise
    falls back to threshold-based checking.
    """
    # Lazy import breaks the cycle: trends.py and detector.py import from utils.py.
    from posthog.tasks.alerts.detector import check_trends_alert_with_detector
    from posthog.tasks.alerts.trends import check_trends_alert

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


def disable_invalid_alert(alert: AlertConfiguration, reason: str) -> None:
    logger.warning("check_alert.auto_disabling", alert_id=alert.id, reason=reason)
    AlertConfiguration.objects.filter(pk=alert.pk).update(
        enabled=False,
        state=AlertState.ERRORED,
        last_checked_at=datetime.now(UTC),
    )
    alert.refresh_from_db()

    targets_to_notify = alert.get_subscribed_users_emails()
    AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=None,
        condition=alert.condition,
        targets_notified={"users": targets_to_notify} if targets_to_notify else {},
        state=AlertState.ERRORED,
        error={"message": reason},
    )
    if targets_to_notify:
        send_notifications_for_disabled(alert, reason, targets_to_notify)


def send_notifications_for_disabled(alert: AlertConfiguration, reason: str, targets: list[str]) -> None:
    logger.info("Sending alert disabled notification", alert_id=alert.id, reason=reason)

    subject = f"PostHog alert {alert.name} has been disabled"
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
        },
    )
    for target in targets:
        message.add_recipient(email=target)

    message.send()
