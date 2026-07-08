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

    The user-facing denial message lives in ``products.slack_app.backend.api``
    next to the Slack-posting helpers, while the quota lookup lives here so
    activity modules can compose both without each one re-importing
    ``ee.billing``. Returns True when the team was blocked and a denial was
    posted.
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


# Reaction errors that should never abort a follow-up activity — the 👀/🔍 reaction is purely
# cosmetic UX feedback, so a deleted/unreachable message or a missing reaction is a no-op.
_BENIGN_REACTION_ERRORS = frozenset({"already_reacted", "message_not_found", "no_reaction", "cant_react"})


def safe_react(client: Any, channel: str, timestamp: str, name: str) -> None:
    try:
        client.reactions_add(channel=channel, timestamp=timestamp, name=name)
    except SlackApiError as e:
        if e.response.get("error") in _BENIGN_REACTION_ERRORS:
            pass
        else:
            raise


def swap_reaction(client: Any, channel: str, timestamp: str, remove: str, add: str) -> None:
    """Replace one reaction with another; a missing old reaction is a no-op."""
    try:
        client.reactions_remove(channel=channel, timestamp=timestamp, name=remove)
    except Exception:
        pass
    safe_react(client, channel, timestamp, add)
