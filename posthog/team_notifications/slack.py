"""Find a team's Slack channel by name, and post an automated message into it.

What every product that posts a routed digest needs: which channel a team's message belongs in, the
limits Slack puts on a message, and what a refused post says. What the message says, and what a
failure does to the product's own records, stay with the product.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

# Slack rejects a section block over 3000 characters. The margin covers the mrkdwn escaping, which
# can turn one character into five.
MAX_SECTION_CHARS = 2900
# Slack's other caps on one message. A block over any of them makes Slack refuse the whole post,
# so a caller that cannot cut the value has to leave the block out.
MAX_HEADER_CHARS = 150
MAX_BUTTON_TEXT_CHARS = 75
MAX_BUTTON_URL_CHARS = 3000
MAX_BLOCKS = 50
# The plain-text fallback. Slack cuts a longer one without saying so, rather than refusing the post.
MAX_TEXT_CHARS = 40_000


def clip_text(text: str, limit: int) -> str:
    """Cut display text down to `limit` characters, marking that something was cut."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


@frozen
class SlackButton:
    """A link button, under a message or beside a section."""

    text: str
    url: str
    primary: bool = False


def _button_element(button: SlackButton) -> dict[str, Any]:
    element: dict[str, Any] = {
        "type": "button",
        # Clipped here rather than at each call site, because Slack refuses the post instead of
        # cutting the label itself.
        "text": {"type": "plain_text", "text": clip_text(button.text, MAX_BUTTON_TEXT_CHARS), "emoji": True},
        "url": button.url,
    }
    if button.primary:
        element["style"] = "primary"
    return element


def header_block(text: str) -> dict[str, Any]:
    """A message's title. Slack renders it as plain text, so mrkdwn in it stays literal."""
    return {"type": "header", "text": {"type": "plain_text", "text": clip_text(text, MAX_HEADER_CHARS), "emoji": True}}


def context_block(text: str) -> dict[str, Any]:
    """A line of small print under whatever it belongs to."""
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def section_block(text: str, button: SlackButton | None = None) -> dict[str, Any]:
    """One mrkdwn section, with a link button on its right when the section has one action."""
    block: dict[str, Any] = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if button is not None:
        block["accessory"] = _button_element(button)
    return block


def fields_block(fields: Sequence[str]) -> dict[str, Any]:
    """A section of short mrkdwn fields, which Slack lays out in two columns."""
    return {"type": "section", "fields": [{"type": "mrkdwn", "text": field} for field in fields]}


def actions_block(buttons: Sequence[SlackButton]) -> dict[str, Any]:
    """A row of link buttons of its own, for actions that belong to the whole message."""
    return {"type": "actions", "elements": [_button_element(button) for button in buttons]}


def divider_block() -> dict[str, Any]:
    return {"type": "divider"}


# Slack channel flags that mark a channel as shared beyond this workspace. A caller that maps a team
# name onto a Slack channel by name can land on a shared channel carrying that name, which sends an
# internal message outside the workspace. is_ext_shared and is_pending_ext_shared cover live and
# pending external connections. is_shared also catches org-shared channels.
SHARED_CHANNEL_FLAGS = ("is_ext_shared", "is_pending_ext_shared", "is_shared")


@frozen
class SlackChannel:
    channel_id: str
    shared: bool


def is_shared_channel(channel: dict) -> bool:
    return any(channel.get(flag) for flag in SHARED_CHANNEL_FLAGS)


def fetch_channel_map(integration: Integration) -> dict[str, SlackChannel]:
    """Public channel name -> channel, for one Slack integration.

    Private channels are skipped: listing them needs a real authed Slack user, and this runs from a
    background task with no request user to act as. Public-only is fine for name matching. The
    shared flag rides along rather than filtering here, because a channel a person named by hand is
    allowed to be shared and a name match is not.
    """
    return {
        channel["name"]: SlackChannel(channel_id=channel["id"], shared=is_shared_channel(channel))
        for channel in SlackIntegration(integration).list_public_channels()
    }


@frozen
class ChannelMatch:
    """One channel lookup, and the reason it found nothing.

    The reason is separate from the channel because the two misses are different problems for
    whoever declared the name: a channel that does not exist is a typo or a rename, and a channel
    the guard refused is a name that would carry the message out of the workspace.
    """

    channel: SlackChannel | None
    reason: Literal["found", "not_found", "shared"]


def find_channel(
    channels_by_name: Mapping[str, SlackChannel], channel_name: str, *, allow_shared: bool
) -> ChannelMatch:
    """Look one channel up by name. The leading ``#`` is optional, because declarations carry it.

    ``allow_shared`` is for a channel a person picked for their own use. A derived or name-matched
    channel keeps the guard on, because that is the path where a message leaves the workspace
    without anybody choosing it.
    """
    channel = channels_by_name.get(channel_name.removeprefix("#"))
    if channel is None:
        return ChannelMatch(channel=None, reason="not_found")
    if channel.shared and not allow_shared:
        return ChannelMatch(channel=None, reason="shared")
    return ChannelMatch(channel=channel, reason="found")


def post_message(
    slack: SlackIntegration,
    channel_id: str,
    blocks: list[dict[str, Any]],
    text: str,
    thread_ts: str | None = None,
) -> SlackResponse:
    # No unfurls: the text is written over untrusted content, so a prompt-injected URL must not make
    # Slack's unfurler fetch an attacker's server from inside the workspace.
    return slack.client.chat_postMessage(
        channel=channel_id,
        blocks=blocks,
        text=text,
        thread_ts=thread_ts,
        unfurl_links=False,
        unfurl_media=False,
    )


def join_channel(slack: SlackIntegration, channel_id: str) -> str | None:
    """Join the channel so the retried post lands. Returns Slack's error code when it refused.

    A channel resolved by name match is one the app was never invited to, which is the normal state
    for a channel nobody set up by hand, so joining is what saves every team a manual ``/invite``.
    Tried rather than gated on the scope: ``conversations.join`` needs ``channels:join``, and
    whether an install granted it is not something the person who set the posting up can see or
    change. Slack answers ``missing_scope`` in under a second, and the caller turns that into an
    error naming the invite.

    ``already_in_channel`` counts as joined: two audiences can resolve to the same channel, so
    another worker may join between this one's failed post and its join, and treating that as a
    refusal would fail a message whose retry would have gone through.
    """
    try:
        slack.client.conversations_join(channel=channel_id)
    except SlackApiError as e:
        error = str(e.response.get("error") or "unknown_error")
        if error == "already_in_channel":
            return None
        logger.warning("team_notifications_slack_join_failed", slack_channel_id=channel_id, error=error)
        return error
    return None


class SlackPostRefused(Exception):
    """The app is not in the channel and could not join it, so nothing was posted."""


def post_with_join(
    slack: SlackIntegration,
    channel_id: str,
    blocks: list[dict[str, Any]],
    text: str,
    *,
    channel_name: str | None = None,
) -> str | None:
    """Post to the channel, joining it first when Slack says the app is not a member.

    Returns the message ts. Every Slack error other than ``not_in_channel`` propagates, because that
    is the only one this can act on.
    """
    try:
        response = post_message(slack, channel_id, blocks, text)
    except SlackApiError as e:
        if e.response.get("error") != "not_in_channel":
            raise
        # Retry once behind the join. A refusal names both Slack's reason and the fix: a person
        # reads this message, and neither "invite the app" nor why the join failed is derivable from
        # a raw Slack error code.
        join_error = join_channel(slack, channel_id)
        if join_error is not None:
            channel = channel_name or channel_id
            raise SlackPostRefused(
                f"Couldn't post to #{channel}. PostHog isn't in the channel and couldn't join it: Slack said "
                f"{join_error}. Invite the app with /invite @PostHog."
            ) from e
        response = post_message(slack, channel_id, blocks, text)

    ts = response.get("ts")
    return str(ts) if ts else None
