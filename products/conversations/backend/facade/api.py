"""
Facade API for conversations.

The only conversations surface other products may import. Wraps the SupportHog
Slack integration behind contract types so callers never touch slack_sdk or the
team's Slack credentials directly.
"""

from typing import Any

from django.conf import settings
from django.db.models import F

from slack_sdk.errors import SlackApiError

from posthog.models.comment import Comment
from posthog.models.team import Team

from products.conversations.backend.facade.types import (
    SupportChannel as SupportChannel,
    TicketSummary as TicketSummary,
)
from products.conversations.backend.models import Ticket
from products.conversations.backend.slack import get_slack_client
from products.conversations.backend.support_slack_channels import (
    SupportSlackChannelsUnavailable as SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured as SupportSlackNotConfigured,
    list_support_bot_channels as _list_support_bot_channels,
)


class SupportMessageSendError(Exception):
    """Slack rejected a SupportHog bot message.

    ``code`` is the Slack error code (e.g. ``not_in_channel``); ``retry_after`` carries
    the requested wait in seconds when Slack rate-limited the post, else None.
    """

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


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
    :class:`SupportMessageSendError` when the post fails.
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
        slack_response = getattr(e, "response", None)
        error_code = str((slack_response or {}).get("error", "unknown"))
        retry_after = None
        # Slack's error code is "ratelimited"; Retry-After is an HTTP header on
        # SlackResponse.headers, not in the JSON body that .get() reads.
        if error_code == "ratelimited":
            raw_retry_after = (getattr(slack_response, "headers", None) or {}).get("Retry-After")
            try:
                retry_after = float(raw_retry_after) if raw_retry_after is not None else None
            except (TypeError, ValueError):
                retry_after = None
        raise SupportMessageSendError(error_code, retry_after=retry_after)
    except Exception:
        # Transport failures (connection/timeout) must not cross the boundary as slack_sdk types.
        raise SupportMessageSendError("transport_error")
    ts = str(response.get("ts") or "")
    if not ts:
        raise SupportMessageSendError("missing_ts")
    return ts


def post_ticket_internal_note(team_id: int, ticket_id: str, content: str, *, dedupe_key: str) -> str | None:
    """Add a team-only note to a ticket, as the AI author. Returns the new comment's id, or None when
    nothing was written because the ticket doesn't exist for this team or this ``dedupe_key`` already
    posted a note.

    Always private: callers use this to hand agent findings to a support teammate, who decides what
    (if anything) reaches the customer. ``dedupe_key`` identifies the thing that produced the note so
    a retrying caller doesn't post twice.
    """
    if not Ticket.objects.filter(team_id=team_id, id=ticket_id).exists():
        return None
    already_posted = Comment.objects.filter(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        item_context__internal_note_key=dedupe_key,
        deleted=False,
    ).exists()
    if already_posted:
        return None
    comment = Comment.objects.create(
        team_id=team_id,
        scope="conversations_ticket",
        item_id=ticket_id,
        content=content,
        item_context={"author_type": "AI", "is_private": True, "internal_note_key": dedupe_key},
    )
    return str(comment.id)


def list_account_tickets(team_id: int, organization_id: str, *, limit: int = 50) -> list[TicketSummary]:
    """Support tickets whose resolved customer org matches ``organization_id``, newest activity first.

    ``organization_id`` is the customer's group key (a customer-analytics account's
    ``external_id``). An empty key matches nothing — never every ticket for the team.
    """
    if not organization_id:
        return []
    tickets = Ticket.objects.filter(team_id=team_id, organization_id=organization_id).order_by(
        F("last_message_at").desc(nulls_last=True)
    )[:limit]
    return [
        TicketSummary(
            id=str(ticket.id),
            ticket_number=ticket.ticket_number,
            status=ticket.status,
            last_message_at=ticket.last_message_at,
            last_message_text=ticket.last_message_text,
            deep_link=f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket.ticket_number}",
        )
        for ticket in tickets
    ]
