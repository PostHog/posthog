"""Shared listing of the SupportHog bot's Slack channels.

Single source of truth for paginating ``conversations_list`` so both the support
ticket-routing picker and the customer-analytics announcements picker (plus its
server-side channel validation) share identical bot-membership semantics instead
of duplicating WebClient logic.
"""

from typing import TYPE_CHECKING, Any, cast

import structlog
from slack_sdk import WebClient

from products.conversations.backend.support_slack import get_support_slack_bot_token

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

MAX_CHANNEL_PAGES = 100


class SupportSlackNotConfigured(Exception):
    """The team has no SupportHog bot token configured."""


class SupportSlackChannelsUnavailable(Exception):
    """The bot's channel list could not be resolved (Slack error or too many pages)."""


def list_support_bot_channels(team: "Team", *, members_only: bool = False) -> list[dict[str, Any]]:
    """Return the SupportHog bot's Slack channels as ``{id, name, is_member}`` dicts.

    With ``members_only=True`` only channels the bot belongs to are returned — the bot
    can only post to those (``chat.postMessage`` returns ``not_in_channel`` otherwise).
    Raises ``SupportSlackNotConfigured`` when no bot token is set; ``slack_sdk``'s
    ``SlackApiError`` propagates to the caller.
    """
    bot_token = get_support_slack_bot_token(team)
    if not bot_token:
        raise SupportSlackNotConfigured()

    client = WebClient(token=bot_token)
    channels: list[dict[str, Any]] = []
    cursor = None

    for _ in range(MAX_CHANNEL_PAGES):
        result = client.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=1000,
            cursor=cursor,
        )
        for c in cast(list[dict[str, Any]], result.get("channels") or []):
            # conversations_list reports is_member for public channels; private channels are
            # only returned when the bot is already in them, so treat a returned private
            # channel as a member channel when the flag is absent.
            is_member = bool(c.get("is_member", c.get("is_private", False)))
            if members_only and not is_member:
                continue
            channels.append({"id": c["id"], "name": c["name"], "is_member": is_member})

        cursor = (result.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
    else:
        logger.warning("support_bot_channels_too_many_pages", max_pages=MAX_CHANNEL_PAGES, team_id=team.pk)
        raise SupportSlackChannelsUnavailable()

    channels.sort(key=lambda c: c["name"].lower())
    return channels
