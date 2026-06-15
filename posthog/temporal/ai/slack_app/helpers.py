"""Shared helpers used across PostHog Slack App Temporal activities.

These helpers exist outside the activity modules so that any activity in
``slack_app.activities.*`` can use them without forcing a cross-module import
between activity files.
"""

from typing import Any

from slack_sdk.errors import SlackApiError


def block_if_team_over_quota(
    *,
    integration: Any,
    slack: Any,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    context: str,
) -> bool:
    """Refuse a Slack-bot turn when the team is over its AI credits quota.

    Tach blocks ``products.slack_app`` from importing ``ee.billing``, so the
    quota lookup lives here (where the temporal layer can freely import ee)
    while the user-facing denial message lives in ``slack_app.backend.api``
    (where the Slack-posting helpers live). Returns True when the team was
    blocked and a denial was posted.
    """
    from products.slack_app.backend.api import post_quota_exhausted_denial

    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

    if not is_team_limited(
        integration.team.api_token,
        QuotaResource.AI_CREDITS,
        QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
    ):
        return False

    post_quota_exhausted_denial(
        integration=integration,
        slack=slack,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        context=context,
    )
    return True


def safe_react(client: Any, channel: str, timestamp: str, name: str) -> None:
    try:
        client.reactions_add(channel=channel, timestamp=timestamp, name=name)
    except SlackApiError as e:
        if e.response.get("error") == "already_reacted":
            pass
        else:
            raise
