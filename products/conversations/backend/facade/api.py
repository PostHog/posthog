"""
Facade API for conversations.

The only conversations surface other products may import. Wraps the SupportHog
Slack integration behind contract types so callers never touch slack_sdk or the
team's Slack credentials directly.
"""

from typing import Any

from slack_sdk.errors import SlackApiError

from posthog.models.team import Team

from products.conversations.backend.facade.contracts import (
    SupportChannel,
    SupportMessageSendError,
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
)
from products.conversations.backend.slack import get_slack_client
from products.conversations.backend.support_slack_channels import (
    list_support_bot_channels as _list_support_bot_channels,
)


def list_support_bot_channels(team_id: int, *, members_only: bool = False) -> list[SupportChannel]:
    """Slack channels the SupportHog bot can see for this team, sorted by name.

    With ``members_only=True``, only channels the bot belongs to (the ones it can
    post to). Raises :class:`SupportSlackNotConfigured` when the bot isn't connected
    and :class:`SupportSlackChannelsUnavailable` when the list can't be resolved.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        raise SupportSlackNotConfigured()
    try:
        channels = _list_support_bot_channels(team, members_only=members_only)
    except (SupportSlackNotConfigured, SupportSlackChannelsUnavailable):
        raise
    except Exception:
        # slack_sdk errors must not cross the boundary as slack_sdk types.
        raise SupportSlackChannelsUnavailable()
    return [SupportChannel(id=c["id"], name=c["name"], is_member=c["is_member"]) for c in channels]


def post_support_message(team_id: int, channel_id: str, text: str) -> str:
    """Post ``text`` to a Slack channel as the SupportHog bot, applying the team's
    configured bot display name and icon. Returns the posted message's Slack ts.

    Raises :class:`SupportSlackNotConfigured` when the bot isn't connected and
    :class:`SupportMessageSendError` when Slack rejects the post.
    """
    try:
        team = Team.objects.get(id=team_id)
        client = get_slack_client(team)
    except (Team.DoesNotExist, ValueError):
        raise SupportSlackNotConfigured()

    message_kwargs: dict[str, Any] = {}
    support_settings = team.conversations_settings or {}
    if bot_display_name := support_settings.get("slack_bot_display_name"):
        message_kwargs["username"] = bot_display_name
    if bot_icon_url := support_settings.get("slack_bot_icon_url"):
        message_kwargs["icon_url"] = bot_icon_url

    try:
        response = client.chat_postMessage(channel=channel_id, text=text, **message_kwargs)
    except SlackApiError as e:
        error_code = str((getattr(e, "response", None) or {}).get("error", "unknown"))
        retry_after = None
        if error_code == "rate_limited":
            raw_retry_after = ((getattr(e, "response", None) or {}).get("headers") or {}).get("Retry-After")
            try:
                retry_after = float(raw_retry_after) if raw_retry_after is not None else None
            except (TypeError, ValueError):
                retry_after = None
        raise SupportMessageSendError(error_code, retry_after=retry_after)
    return str(response.get("ts") or "")
