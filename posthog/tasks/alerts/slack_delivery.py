from datetime import UTC, datetime, timedelta

import structlog

from posthog.api.hog_invocation_results import fetch_hog_invocation_results
from posthog.email import EmailMessage

from products.alerts.backend.models.alert import AlertConfiguration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType

logger = structlog.get_logger(__name__)

# Slack error codes that won't self-heal without the alert owner acting — the bot isn't in the
# channel, the token is dead, the channel is gone. Mirrors the subscription path's
# SLACK_USER_CONFIG_ERRORS (ee/tasks/subscriptions/__init__.py) so the CDP-based alert path
# surfaces the same failures that subscriptions already auto-report.
SLACK_USER_CONFIG_ERRORS = frozenset(
    {"not_in_channel", "account_inactive", "is_archived", "channel_not_found", "invalid_auth", "token_revoked"}
)

# Human-readable guidance per Slack error code, shown to the alert owner in the email.
_SLACK_ERROR_REASONS: dict[str, str] = {
    "not_in_channel": (
        "The PostHog Slack app isn't a member of the target channel. Invite it to the channel — "
        "for private channels the app must be added explicitly."
    ),
    "channel_not_found": "The target Slack channel no longer exists or the PostHog Slack app can't see it.",
    "is_archived": "The target Slack channel is archived.",
    "invalid_auth": "The Slack connection is no longer valid. Reconnect the Slack integration in your project settings.",
    "token_revoked": "The Slack connection was revoked. Reconnect the Slack integration in your project settings.",
    "account_inactive": "The Slack workspace connection is inactive. Reconnect the Slack integration in your project settings.",
}

# How far back to look for the previous firing's Slack delivery result. Alert intervals are
# >= 15 minutes, so the prior firing's HogFunction has long finished; 8 days covers weekly alerts.
_LOOKBACK = timedelta(days=8)


def _linked_slack_hog_functions(alert: AlertConfiguration) -> list[HogFunction]:
    """Internal-destination HogFunctions this alert fires into (matched by the alert_id filter)."""
    return list(
        HogFunction.objects.filter(
            team_id=alert.team_id,
            type=HogFunctionType.INTERNAL_DESTINATION,
            deleted=False,
            enabled=True,
            filters__contains={"properties": [{"key": "alert_id", "value": str(alert.id)}]},
        )
    )


def _match_slack_config_error(error_message: str | None) -> str | None:
    if not error_message:
        return None
    lowered = error_message.lower()
    return next((code for code in SLACK_USER_CONFIG_ERRORS if code in lowered), None)


def _latest_slack_config_failure(team_id: int, function_id: str) -> str | None:
    """Return the Slack config error code if the destination's MOST RECENT delivery failed, else None.

    We check the latest invocation (not just the latest *failed* one) so a since-recovered
    destination doesn't keep alerting — the current delivery state is what matters.
    """
    try:
        results = fetch_hog_invocation_results(
            team_id=team_id,
            function_kind="hog_function",
            function_id=function_id,
            limit=1,
            after=datetime.now(UTC) - _LOOKBACK,
        )
    except Exception:
        # A failed observability lookup must never break the actual alert notification.
        logger.warning(
            "alerts.slack_delivery_check_query_failed", team_id=team_id, function_id=function_id, exc_info=True
        )
        return None

    if not results or results[0].status != "failed":
        return None
    return _match_slack_config_error(results[0].error_message)


def check_and_notify_slack_delivery_failures(alert: AlertConfiguration) -> None:
    """Surface a failed Slack HogFunction delivery from the alert's previous firing to its owner.

    The alert Slack path (produce ``$insight_alert_firing`` -> CDP HogFunction ``fetch``) is
    fire-and-forget: a Slack config error (bot not in channel, revoked token, ...) errors deep in
    the CDP pipeline and never reaches the alert owner, unlike Slack *subscriptions* which
    auto-report via SLACK_USER_CONFIG_ERRORS. This closes that gap by reading the linked
    destination's most recent invocation result and emailing subscribers when it failed for a
    reason only they can fix.

    Feedback lands on the alert's next firing (the prior firing's delivery has finished by then).
    A one-shot fire that never fires again won't get a mail — acceptable, since the recurring
    case is what leaves owners guessing.
    """
    targets = alert.get_subscribed_users_emails()
    if not targets:
        return

    for hog_function in _linked_slack_hog_functions(alert):
        error_code = _latest_slack_config_failure(alert.team_id, str(hog_function.id))
        if error_code is None:
            continue
        _send_slack_delivery_failure_email(alert, str(hog_function.id), error_code, targets)


def _send_slack_delivery_failure_email(
    alert: AlertConfiguration, hog_function_id: str, error_code: str, targets: list[str]
) -> None:
    reason = _SLACK_ERROR_REASONS.get(error_code, f"Slack rejected the message with error '{error_code}'.")
    logger.info(
        "alerts.slack_delivery_failure_notification",
        alert_id=str(alert.id),
        hog_function_id=hog_function_id,
        error_code=error_code,
    )

    insight_url = f"/project/{alert.team.pk}/insights/{alert.insight.short_id}"
    alert_url = f"{insight_url}?alert_id={alert.id}"
    # Dedup per (alert, destination, error code): one email per distinct failure, so a persistently
    # broken destination doesn't mail on every firing but a new/different failure still surfaces.
    campaign_key = f"alert-slack-delivery-failure-{alert.id}-{hog_function_id}-{error_code}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog alert {alert.name} can't deliver to Slack",
        template_name="alert_slack_delivery_failing",
        template_context={
            "alert_url": alert_url,
            "alert_name": alert.name,
            "insight_url": insight_url,
            "insight_name": alert.insight.name,
            "slack_error_reason": reason,
        },
    )
    for target in targets:
        message.add_recipient(email=target)
    message.send()
