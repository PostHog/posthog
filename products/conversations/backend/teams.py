"""
Microsoft Teams inbound handler for the support/conversations product.

Handles two triggers that create or update tickets from Teams:
1. Dedicated channel: messages in a configured support channel (via RSC permission)
2. Bot mention: @mention the bot to create a ticket

Both converge to create_or_update_teams_ticket().
"""

import uuid
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.db.models import F

import requests
import structlog

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from .cache import get_cached_teams_user, set_cached_teams_user
from .models import Ticket
from .models.constants import Channel, ChannelDetail, Status
from .support_teams import (
    get_bot_framework_token,
    get_bot_from_id,
    get_graph_token,
    invalidate_bot_framework_token,
    is_trusted_teams_service_url,
)
from .teams_formatting import teams_html_to_content_and_rich_content

logger = structlog.get_logger(__name__)

_UNKNOWN_USER = MappingProxyType({"name": "Unknown", "email": None})
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


def _get_team_id(team: Team) -> int:
    team_id = getattr(team, "id", None)
    if not isinstance(team_id, int):
        raise ValueError("Invalid team id")
    return team_id


def resolve_teams_user(tenant_id: str, teams_user_id: str, team: Team, fallback_name: str = "") -> dict:
    """Resolve a Teams user AAD object ID to name and email via Graph API. Cached in Redis for 5 min.

    ``fallback_name`` should be ``activity.from.name`` — Teams always populates
    that with the user's display name as visible in the channel, so it's a
    better default than "Unknown" when Graph is unreachable or the tenant's
    user-read policy blocks /users/{id} lookups with our delegated scopes.
    """
    unknown = {"name": fallback_name or _UNKNOWN_USER["name"], "email": None}

    if not teams_user_id:
        return dict(unknown)

    try:
        normalized_user_id = str(uuid.UUID(teams_user_id))
    except (ValueError, TypeError, AttributeError):
        logger.warning("teams_user_resolve_invalid_id", teams_user_id=teams_user_id)
        return dict(unknown)

    cached = get_cached_teams_user(tenant_id, normalized_user_id)
    if cached is not None:
        return cached

    try:
        token = get_graph_token(team)
        resp = requests.get(
            f"{GRAPH_API_BASE}/users/{quote(normalized_user_id, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "displayName,mail,userPrincipalName"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(
                "teams_user_resolve_failed",
                teams_user_id=normalized_user_id,
                status=resp.status_code,
                body=resp.text[:300],
            )
            return dict(unknown)

        data = resp.json()
        result = {
            "name": data.get("displayName") or fallback_name or "Unknown",
            "email": data.get("mail") or data.get("userPrincipalName"),
        }
        set_cached_teams_user(tenant_id, normalized_user_id, result)
        return result
    except Exception:
        logger.warning("teams_user_resolve_error", teams_user_id=normalized_user_id)
        return dict(unknown)


def resolve_posthog_user_for_teams(email: str | None, team: Team) -> User | None:
    """Match a Teams user's email to a PostHog user within the team's organization."""
    if not email:
        return None
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__email=email,
        )
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def _extract_user_id_from_activity(activity: dict) -> str:
    """Extract the AAD object ID of the message sender from an Activity."""
    from_field = activity.get("from") or {}
    aad_id = from_field.get("aadObjectId", "")
    return aad_id


def _extract_user_name_from_activity(activity: dict) -> str:
    """Extract the display name of the message sender from an Activity."""
    from_field = activity.get("from") or {}
    return from_field.get("name", "") or ""


def _extract_conversation_id(activity: dict) -> str:
    """Extract the conversation (reply chain) ID from an Activity."""
    conversation = activity.get("conversation") or {}
    return conversation.get("id", "")


def _extract_channel_id(activity: dict) -> str:
    """Extract the Teams channel ID from an Activity's channelData."""
    channel_data = activity.get("channelData") or {}
    team_channel = channel_data.get("channel") or {}
    return team_channel.get("id", "")


def _is_reply(activity: dict) -> bool:
    """Check if this activity is a reply in an existing channel thread.

    In Teams channels, every message's conversation.id contains
    `;messageid=<root-id>` — even brand-new top-level posts. The difference:
      - top-level: root-id == activity.id
      - thread reply: root-id != activity.id (and typically replyToId is set)

    So we can't use `;messageid=` presence alone to detect a reply.
    """
    if activity.get("replyToId"):
        return True
    conversation_id = _extract_conversation_id(activity)
    activity_id = activity.get("id", "")
    if ";messageid=" in conversation_id and activity_id:
        root_id = conversation_id.split(";messageid=", 1)[1]
        return root_id != activity_id
    return False


def _is_bot_mention(activity: dict) -> bool:
    """Check if the bot was @mentioned in this activity."""
    try:
        bot_from_id = get_bot_from_id()
    except ValueError:
        return False

    entities = activity.get("entities") or []
    for entity in entities:
        if entity.get("type") == "mention":
            mentioned = entity.get("mentioned") or {}
            if mentioned.get("id") == bot_from_id:
                return True
    return False


def _send_confirmation_card(
    service_url: str,
    conversation_id: str,
    reply_to_id: str | None,
    ticket: Ticket,
    team: Team,
) -> None:
    """Post a ticket confirmation Adaptive Card as a reply in Teams."""
    if not is_trusted_teams_service_url(service_url):
        logger.warning("teams_confirmation_untrusted_service_url", ticket_id=str(ticket.id), service_url=service_url)
        return

    team_id = _get_team_id(team)
    ticket_url = f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket.id}"

    try:
        bot_token = get_bot_framework_token()
        bot_from_id = get_bot_from_id()
    except ValueError:
        logger.warning("teams_confirmation_no_bot_token", ticket_id=str(ticket.id))
        return

    payload: dict[str, Any] = {
        "type": "message",
        "from": {"id": bot_from_id},
        "conversation": {"id": conversation_id},
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"\U0001f3ab Ticket #{ticket.ticket_number} created",
                            "weight": "Bolder",
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "View in PostHog",
                            "url": ticket_url,
                        }
                    ],
                },
            }
        ],
    }
    if reply_to_id:
        payload["replyToId"] = reply_to_id

    encoded_conversation_id = quote(conversation_id, safe="")
    url = f"{service_url.rstrip('/')}/v3/conversations/{encoded_conversation_id}/activities"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
            timeout=15,
        )
        # Bot Connector 401 often means a stale cached token (e.g. after a deploy
        # or secret rotation). Drop the cache and retry once with a fresh token.
        if resp.status_code == 401:
            invalidate_bot_framework_token()
            try:
                bot_token = get_bot_framework_token(force_refresh=True)
            except ValueError:
                logger.warning("teams_confirmation_no_bot_token_on_retry", ticket_id=str(ticket.id))
                return
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
                timeout=15,
            )
        if resp.status_code not in (200, 201):
            logger.warning(
                "teams_confirmation_post_failed",
                ticket_id=str(ticket.id),
                status=resp.status_code,
                body=resp.text[:500],
                url=url,
            )
    except Exception:
        logger.warning("teams_confirmation_post_error", ticket_id=str(ticket.id))


def create_or_update_teams_ticket(
    *,
    team: Team,
    activity: dict,
    tenant_id: str,
    is_thread_reply: bool = False,
    channel_detail: ChannelDetail | None = None,
) -> Ticket | None:
    """
    Core function: create a new ticket or add a message to an existing one from a Teams Activity.

    For new tickets (is_thread_reply=False):
      - Creates Ticket with channel_source="teams"
      - Creates first Comment
      - Posts a confirmation Adaptive Card

    For thread replies (is_thread_reply=True):
      - Finds existing Ticket by teams_channel_id + teams_conversation_id
      - Creates a new Comment on that ticket
    """
    team_id = _get_team_id(team)
    service_url = activity.get("serviceUrl", "")
    conversation_id = _extract_conversation_id(activity)
    channel_id = _extract_channel_id(activity)
    teams_user_id = _extract_user_id_from_activity(activity)
    teams_user_name = _extract_user_name_from_activity(activity)
    text_html = activity.get("text", "")
    activity_id = activity.get("id", "")

    logger.info(
        "teams_ticket_ingest_started",
        team_id=team_id,
        channel_id=channel_id,
        conversation_id=conversation_id,
        is_thread_reply=is_thread_reply,
    )

    # Resolve Teams user to name + email. `teams_user_name` comes from
    # activity.from.name and is used as a fallback when Graph can't return the
    # profile (e.g. the tenant restricts /users/{id} reads for our delegated
    # scopes, or the Graph call fails transiently).
    user_info = resolve_teams_user(tenant_id, teams_user_id, team, fallback_name=teams_user_name)
    posthog_user = resolve_posthog_user_for_teams(user_info.get("email"), team)
    is_team_member = posthog_user is not None

    # Convert Teams HTML to content and rich_content
    cleaned_text, rich_content = teams_html_to_content_and_rich_content(text_html)

    if not cleaned_text:
        logger.warning("teams_ticket_ingest_empty", team_id=team_id, activity_id=activity_id)
        return None

    if is_thread_reply:
        ticket = Ticket.objects.filter(
            team=team,
            teams_channel_id=channel_id,
            teams_conversation_id=conversation_id,
        ).first()

        if not ticket:
            logger.debug(
                "teams_thread_reply_no_ticket",
                channel_id=channel_id,
                conversation_id=conversation_id,
            )
            return None

        Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=cleaned_text,
            rich_content=rich_content,
            created_by=posthog_user,
            item_context={
                "author_type": "support" if is_team_member else "customer",
                "is_private": False,
                "from_teams": True,
                "teams_user_id": teams_user_id,
                "teams_author_name": user_info["name"],
                "teams_author_email": user_info.get("email"),
            },
        )

        if not is_team_member:
            Ticket.objects.filter(id=ticket.id, team=team).update(
                unread_team_count=F("unread_team_count") + 1,
            )

        return ticket

    # New ticket from top-level message.
    # Thread replies will have conversation.id = "<channel>;messageid=<root_msg_id>".
    # Store that form so reply lookups match.
    thread_conversation_id = (
        f"{conversation_id};messageid={activity_id}"
        if activity_id and ";messageid=" not in conversation_id
        else conversation_id
    )

    # Defense against replays after idempotency cache expiry: if a ticket
    # already exists for this normalized thread id, treat this as a thread
    # reply rather than creating a duplicate.
    existing_ticket = Ticket.objects.filter(
        team=team,
        teams_channel_id=channel_id,
        teams_conversation_id=thread_conversation_id,
    ).first()
    if existing_ticket:
        logger.info(
            "teams_ticket_ingest_duplicate_root_skipped",
            team_id=team_id,
            channel_id=channel_id,
            conversation_id=thread_conversation_id,
            ticket_id=str(existing_ticket.id),
        )
        return existing_ticket

    ticket = Ticket.objects.create_with_number(
        team=team,
        channel_source=Channel.TEAMS,
        channel_detail=channel_detail,
        widget_session_id="",
        distinct_id=user_info.get("email") or "",
        status=Status.NEW,
        anonymous_traits={
            "name": user_info["name"],
            **({"email": user_info["email"]} if user_info.get("email") else {}),
        },
        teams_channel_id=channel_id,
        teams_conversation_id=thread_conversation_id,
        teams_service_url=service_url,
        teams_tenant_id=tenant_id,
        unread_team_count=0 if is_team_member else 1,
    )

    Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=cleaned_text,
        rich_content=rich_content,
        created_by=posthog_user,
        item_context={
            "author_type": "support" if is_team_member else "customer",
            "is_private": False,
            "from_teams": True,
            "teams_user_id": teams_user_id,
            "teams_author_name": user_info["name"],
            "teams_author_email": user_info.get("email"),
        },
    )

    # Post confirmation card in the Teams thread
    _send_confirmation_card(
        service_url=service_url,
        conversation_id=conversation_id,
        reply_to_id=activity_id,
        ticket=ticket,
        team=team,
    )

    return ticket


def handle_teams_message(activity: dict, team: Team, tenant_id: str) -> None:
    """
    Handle a Teams message activity for the dedicated support channel.

    Top-level messages create new tickets.
    Thread replies add messages to existing tickets.
    """
    channel_id = _extract_channel_id(activity)
    if not channel_id:
        return

    # Skip messages the bot sent itself.
    from_field = activity.get("from") or {}
    try:
        bot_from_id = get_bot_from_id()
    except ValueError:
        bot_from_id = ""
    if bot_from_id and from_field.get("id") == bot_from_id:
        return

    settings_dict = team.conversations_settings or {}
    configured_channel = settings_dict.get("teams_channel_id")

    conversation_id = _extract_conversation_id(activity)
    is_reply = _is_reply(activity)

    if is_reply:
        # Thread replies sync if ticket exists, even outside dedicated channel
        if not Ticket.objects.filter(
            team=team, teams_channel_id=channel_id, teams_conversation_id=conversation_id
        ).exists():
            if not configured_channel or configured_channel != channel_id:
                return

        create_or_update_teams_ticket(
            team=team,
            activity=activity,
            tenant_id=tenant_id,
            is_thread_reply=True,
        )
        return

    if not configured_channel or configured_channel != channel_id:
        return

    # Top-level message -> create new ticket
    create_or_update_teams_ticket(
        team=team,
        activity=activity,
        tenant_id=tenant_id,
        is_thread_reply=False,
        channel_detail=ChannelDetail.TEAMS_CHANNEL_MESSAGE,
    )


def handle_teams_mention(activity: dict, team: Team, tenant_id: str) -> None:
    """
    Handle a Teams @mention activity to create a support ticket.

    The mention message becomes the first message of the ticket.
    """
    channel_id = _extract_channel_id(activity)
    if not channel_id:
        return

    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("teams_enabled"):
        return

    conversation_id = _extract_conversation_id(activity)
    activity_id = activity.get("id", "")

    # Top-level mentions get stored as "<conv>;messageid=<activity_id>" so that
    # subsequent thread replies (which arrive with that full form) match.
    # Check both forms here so a reprocessed/replayed activity won't create a
    # duplicate ticket after the idempotency cache expires.
    candidate_conversation_ids = [conversation_id]
    if activity_id and ";messageid=" not in conversation_id:
        candidate_conversation_ids.append(f"{conversation_id};messageid={activity_id}")

    existing = Ticket.objects.filter(
        team=team,
        teams_channel_id=channel_id,
        teams_conversation_id__in=candidate_conversation_ids,
    ).exists()

    create_or_update_teams_ticket(
        team=team,
        activity=activity,
        tenant_id=tenant_id,
        is_thread_reply=existing,
        channel_detail=ChannelDetail.TEAMS_BOT_MENTION,
    )
