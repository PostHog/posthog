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
from .services.attachments import build_content_with_images
from .support_teams import (
    get_bot_framework_token,
    get_bot_from_id,
    get_graph_token,
    invalidate_bot_framework_token,
    is_teams_graph_message_seen,
    is_trusted_teams_service_url,
    mark_teams_graph_message_seen,
)
from .teams_attachments import extract_teams_bot_attachments
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


_HELP_CARD_BODY = [
    {
        "type": "TextBlock",
        "text": "\U0001f44b Hi, I'm SupportHog",
        "weight": "Bolder",
        "size": "Medium",
    },
    {
        "type": "TextBlock",
        "text": (
            "I turn Teams messages into PostHog support tickets, so you don't have to log into four different systems at once to answer one question. \n\n"
            "You can open a new ticket anywhere by tagging me with an @mention. I'll sync replies from threads. You can set up dedicated support channels in PostHog settings too!\n\n"
            "Need help in the future? Just say '@SupportHog help' to get this message again."
        ),
        "wrap": True,
    },
]


def _build_help_card() -> dict[str, Any]:
    """Help/welcome adaptive card. No action button — Teams users are customers,
    not PostHog operators, so an "Open PostHog" link would 404 for them."""
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.2",
            "body": _HELP_CARD_BODY,
        },
    }


def _post_activity_to_conversation(
    *,
    service_url: str,
    conversation_id: str,
    payload: dict[str, Any],
    log_prefix: str,
    log_context: dict[str, Any] | None = None,
) -> bool:
    """Shared bot-framework outbound POST with 401 retry and trusted-URL check."""
    if not is_trusted_teams_service_url(service_url):
        logger.warning(f"{log_prefix}_untrusted_service_url", service_url=service_url, **(log_context or {}))
        return False

    try:
        bot_token = get_bot_framework_token()
    except ValueError:
        logger.warning(f"{log_prefix}_no_bot_token", **(log_context or {}))
        return False

    encoded_conversation_id = quote(conversation_id, safe="")
    url = f"{service_url.rstrip('/')}/v3/conversations/{encoded_conversation_id}/activities"

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 401:
            invalidate_bot_framework_token()
            try:
                bot_token = get_bot_framework_token(force_refresh=True)
            except ValueError:
                logger.warning(f"{log_prefix}_no_bot_token_on_retry", **(log_context or {}))
                return False
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
                timeout=15,
            )
        if resp.status_code not in (200, 201):
            logger.warning(
                f"{log_prefix}_post_failed",
                status=resp.status_code,
                body=resp.text[:500],
                url=url,
                **(log_context or {}),
            )
            return False
        return True
    except Exception:
        logger.warning(f"{log_prefix}_post_error", **(log_context or {}))
        return False


def is_bot_added_event(activity: dict) -> bool:
    """True if this conversationUpdate adds the bot itself to a team/conversation."""
    if activity.get("type") != "conversationUpdate":
        return False
    recipient_id = (activity.get("recipient") or {}).get("id", "")
    if not recipient_id:
        return False
    members_added = activity.get("membersAdded") or []
    return any(m.get("id") == recipient_id for m in members_added)


_GREETING_COMMANDS = frozenset({"hi", "hello", "hey", "hola", "yo", "help", "?", "start", "get started", "supporthog"})


def is_command_message(activity: dict) -> bool:
    """Return True if the @mention text is a recognized greeting/help command."""
    raw_html = activity.get("text", "") or ""
    cleaned, _ = teams_html_to_content_and_rich_content(raw_html)
    normalized = cleaned.strip().lower().rstrip("!.?")
    return normalized in _GREETING_COMMANDS


def post_help_card(activity: dict, *, log_prefix: str, reply: bool) -> bool:
    """Post the help/welcome adaptive card to a conversation.

    Used for both the cert-mandated proactive welcome on bot install
    (``reply=False``) and the cert-mandated reply to greeting/help commands
    (``reply=True``). Returns ``True`` when the card was posted *or* when
    retrying would not help (malformed activity, bot config missing). Returns
    ``False`` only on transient transport failures (5xx, timeouts) so the
    caller's retry budget is reserved for cases where retrying could fix it.
    """
    service_url = activity.get("serviceUrl", "")
    conversation_id = _extract_conversation_id(activity)
    if not (service_url and conversation_id):
        return True

    try:
        bot_from_id = get_bot_from_id()
    except ValueError:
        logger.warning(f"{log_prefix}_no_bot_id")
        return True

    payload: dict[str, Any] = {
        "type": "message",
        "from": {"id": bot_from_id},
        "conversation": {"id": conversation_id},
        "attachments": [_build_help_card()],
    }
    if reply:
        activity_id = activity.get("id", "")
        if activity_id:
            payload["replyToId"] = activity_id

    return _post_activity_to_conversation(
        service_url=service_url,
        conversation_id=conversation_id,
        payload=payload,
        log_prefix=log_prefix,
    )


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


# Graph's channel membershipType is an evolvable enum: the v1.0
# /teams/{id}/channels endpoint emits "unknownFutureValue" for shared channels in
# some tenants instead of the literal "shared". We treat anything that isn't an
# explicit standard/private channel as shared (poll + Graph-post), and Graph
# re-verification elsewhere rejects only the explicit standard/private cases.
TEAMS_NON_POLLED_MEMBERSHIP_TYPES = {"standard", "private"}


def is_shared_membership_type(membership_type: str | None) -> bool:
    return membership_type not in TEAMS_NON_POLLED_MEMBERSHIP_TYPES


def parse_teams_root_message_id(conversation_id: str | None) -> str | None:
    """Extract the Graph root message id from a ``<channel>;messageid=<id>`` conversation id."""
    if not conversation_id:
        return None
    marker = ";messageid="
    if marker not in conversation_id:
        return None
    return conversation_id.split(marker, 1)[1] or None


def resolve_shared_channel_team_id(team: Team, channel_id: str | None) -> str | None:
    """Return the Graph teamId (group id) for a configured *shared* channel, else ``None``.

    Shared/private channels are written to via Graph (delegated admin token), not the
    bot connector, so this both selects the transport and supplies the teamId the Graph
    messages endpoint needs (the ticket itself doesn't store the group id).
    """
    if not channel_id:
        return None
    settings_dict = team.conversations_settings or {}
    entries = settings_dict.get("teams_channels")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("channel_id") != channel_id:
            continue
        if not is_shared_membership_type(entry.get("membership_type")):
            return None
        team_group_id = entry.get("team_id")
        return str(team_group_id) if team_group_id else None
    return None


def post_teams_channel_message_via_graph(
    *,
    team: Team,
    teams_team_id: str,
    channel_id: str,
    html: str,
    reply_to_message_id: str | None = None,
    token: str | None = None,
    log_context: dict | None = None,
) -> tuple[int, str | None]:
    """Post an HTML channel message (or thread reply) via Graph as the connecting admin.

    The bot connector can't write to shared channels (the bot isn't a member), so
    confirmation cards and agent replies for shared-channel tickets go through Graph
    with the same delegated token the poller uses to read. Returns ``(status, message_id)``
    where status is the HTTP status code (``0`` for a missing token or network error)
    and ``message_id`` is the created chatMessage id on success.
    """
    ctx = log_context or {}
    if token is None:
        try:
            token = get_graph_token(team)
        except ValueError:
            logger.warning("teams_graph_post_no_token", **ctx)
            return 0, None

    base = f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}/messages"
    url = f"{base}/{reply_to_message_id}/replies" if reply_to_message_id else base
    try:
        resp = requests.post(
            url,
            json={"body": {"contentType": "html", "content": html}},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
    except requests.RequestException:
        logger.warning("teams_graph_post_error", url=url, **ctx)
        return 0, None

    message_id: str | None = None
    if resp.status_code in (200, 201):
        try:
            raw_id = resp.json().get("id")
            message_id = str(raw_id) if raw_id else None
        except (ValueError, AttributeError, TypeError):
            message_id = None
        if message_id:
            mark_teams_graph_message_seen(_get_team_id(team), channel_id, message_id)
    else:
        logger.warning("teams_graph_post_failed", status=resp.status_code, body=resp.text[:500], url=url, **ctx)
    return resp.status_code, message_id


def create_or_update_teams_ticket(
    *,
    team: Team,
    activity: dict,
    tenant_id: str,
    is_thread_reply: bool = False,
    channel_detail: ChannelDetail | None = None,
    graph_post_context: dict | None = None,
    images: list[dict[str, Any]] | None = None,
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

    # Merge extracted images into content + rich_content
    resolved_images = images or []
    if resolved_images:
        cleaned_text, rich_content = build_content_with_images(cleaned_text, rich_content, resolved_images)

    if not cleaned_text and not resolved_images:
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

        if activity_id and is_teams_graph_message_seen(team_id, channel_id, activity_id):
            logger.debug(
                "teams_thread_reply_duplicate_skipped",
                team_id=team_id,
                activity_id=activity_id,
                ticket_id=str(ticket.id),
            )
            return ticket

        if (
            activity_id
            and Comment.objects.filter(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                item_context__teams_graph_message_id=activity_id,
            ).exists()
        ):
            mark_teams_graph_message_seen(team_id, channel_id, activity_id)
            return ticket

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
                "teams_graph_message_id": activity_id,
                "teams_images": resolved_images if resolved_images else None,
            },
        )
        mark_teams_graph_message_seen(team_id, channel_id, activity_id)

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
        # Created from a signature-validated Teams webhook — platform-attested identity.
        identity_verified=True,
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
            "teams_graph_message_id": activity_id,
            "teams_images": resolved_images if resolved_images else None,
        },
    )

    if activity_id:
        mark_teams_graph_message_seen(team_id, channel_id, activity_id)

    # Post confirmation card in the Teams thread. Shared-channel tickets (polled)
    # can't be confirmed over the bot connector, so go through Graph instead.
    if graph_post_context:
        ticket_url = f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket.id}"
        post_teams_channel_message_via_graph(
            team=team,
            teams_team_id=graph_post_context["teams_team_id"],
            channel_id=channel_id,
            html=f'\U0001f3ab Ticket #{ticket.ticket_number} created. <a href="{ticket_url}">View in PostHog</a>',
            reply_to_message_id=activity_id,
            token=graph_post_context.get("token"),
            log_context={"ticket_id": str(ticket.id)},
        )
    else:
        _send_confirmation_card(
            service_url=service_url,
            conversation_id=conversation_id,
            reply_to_id=activity_id,
            ticket=ticket,
            team=team,
        )

    return ticket


def _configured_support_channel_ids(settings: dict) -> set[str]:
    """Return the set of Teams channel IDs configured for auto-ticket creation.

    Merges the new ``teams_channels`` list with the legacy scalar
    ``teams_channel_id`` so that teams that haven't re-saved settings after
    the multi-channel migration still work.
    """
    ids: set[str] = set()
    teams_channels = settings.get("teams_channels")
    if isinstance(teams_channels, list):
        for entry in teams_channels:
            if isinstance(entry, dict):
                channel_id = entry.get("channel_id")
                if channel_id:
                    ids.add(channel_id)
    legacy = settings.get("teams_channel_id")
    if legacy:
        ids.add(legacy)
    return ids


def _extract_bot_images(activity: dict, team: Team) -> list[dict[str, Any]]:
    """Best-effort extraction of image attachments from a bot-framework activity."""
    attachments = activity.get("attachments")
    if not attachments:
        return []
    try:
        bot_token = get_bot_framework_token()
    except ValueError:
        return []
    return extract_teams_bot_attachments(attachments, team, bot_token)


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
    configured_channels = _configured_support_channel_ids(settings_dict)

    conversation_id = _extract_conversation_id(activity)
    is_reply = _is_reply(activity)

    if is_reply:
        # Thread replies sync if ticket exists, even outside dedicated channel
        if not Ticket.objects.filter(
            team=team, teams_channel_id=channel_id, teams_conversation_id=conversation_id
        ).exists():
            if channel_id not in configured_channels:
                return

        images = _extract_bot_images(activity, team)
        create_or_update_teams_ticket(
            team=team,
            activity=activity,
            tenant_id=tenant_id,
            is_thread_reply=True,
            images=images,
        )
        return

    if channel_id not in configured_channels:
        return

    # Top-level message -> create new ticket
    images = _extract_bot_images(activity, team)
    create_or_update_teams_ticket(
        team=team,
        activity=activity,
        tenant_id=tenant_id,
        is_thread_reply=False,
        channel_detail=ChannelDetail.TEAMS_CHANNEL_MESSAGE,
        images=images,
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

    # Greeting/help commands (cert 11.4.4.3) reply with the help card and do
    # NOT create a ticket — otherwise testers typing "Hi" generate noise.
    if is_command_message(activity):
        post_help_card(activity, log_prefix="teams_help_reply", reply=True)
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

    images = _extract_bot_images(activity, team)
    create_or_update_teams_ticket(
        team=team,
        activity=activity,
        tenant_id=tenant_id,
        is_thread_reply=existing,
        channel_detail=ChannelDetail.TEAMS_BOT_MENTION,
        images=images,
    )


def graph_message_to_activity(msg: dict, channel_id: str, service_url: str) -> dict | None:
    """Map a Microsoft Graph ``chatMessage`` (from channel ``messages/delta``) to the
    Bot Framework activity shape that ``create_or_update_teams_ticket`` consumes.

    Returns ``None`` for anything we don't ingest as a top-level support message:
    non-message types (system events), deletions, replies, empty bodies, and
    system/bot/app-authored posts (no ``from.user``). The mapped activity uses the
    canonical ``"<channelId>;messageid=<msgId>"`` conversation id so a later webhook
    reply on the same thread dedupes onto the same ticket.
    """
    # Only real user messages: skip systemEventMessage, typing, etc.
    if msg.get("messageType") != "message":
        return None
    if msg.get("deletedDateTime"):
        return None
    # Channel messages/delta returns root messages only; guard defensively in case
    # a reply ever shows up (thread replies are ingested via the reply poller).
    if msg.get("replyToId"):
        return None

    body = msg.get("body") or {}
    content = body.get("content") or ""
    has_hosted_images = bool(msg.get("hostedContents"))
    if not content.strip() and not has_hosted_images:
        return None

    # System/bot/app posts (incl. our own confirmation cards) carry from.application
    # or from.device, never from.user — skip them so we never self-ingest.
    from_field = msg.get("from") or {}
    user = from_field.get("user") or {}
    aad_object_id = user.get("id")
    if not aad_object_id:
        return None

    msg_id = msg.get("id")
    if not msg_id:
        return None

    return {
        "id": msg_id,
        "type": "message",
        "text": content,
        "from": {
            "id": aad_object_id,
            "aadObjectId": aad_object_id,
            "name": user.get("displayName") or "",
        },
        "conversation": {"id": f"{channel_id};messageid={msg_id}"},
        "channelData": {"channel": {"id": channel_id}},
        "serviceUrl": service_url,
    }


def graph_reply_to_activity(
    msg: dict,
    channel_id: str,
    root_message_id: str,
    service_url: str,
) -> dict | None:
    """Map a Graph thread ``chatMessage`` reply to a Bot Framework activity shape.

    Used by the shared-channel reply poller. The activity uses the ticket's canonical
    ``"<channelId>;messageid=<rootId>"`` conversation id so ``create_or_update_teams_ticket``
    finds the existing ticket with ``is_thread_reply=True``.
    """
    msg_id = msg.get("id")
    if msg.get("messageType") != "message":
        logger.debug(
            "teams_reply_skipped",
            reason="not_a_message",
            channel_id=channel_id,
            root_message_id=root_message_id,
            msg_id=msg_id,
            message_type=msg.get("messageType"),
        )
        return None
    if msg.get("deletedDateTime"):
        logger.debug(
            "teams_reply_skipped",
            reason="deleted",
            channel_id=channel_id,
            root_message_id=root_message_id,
            msg_id=msg_id,
        )
        return None

    body = msg.get("body") or {}
    content = body.get("content") or ""
    has_hosted_images = bool(msg.get("hostedContents"))
    if not content.strip() and not has_hosted_images:
        logger.debug(
            "teams_reply_skipped",
            reason="empty_content",
            channel_id=channel_id,
            root_message_id=root_message_id,
            msg_id=msg_id,
        )
        return None

    from_field = msg.get("from") or {}
    user = from_field.get("user") or {}
    aad_object_id = user.get("id")
    if not aad_object_id:
        logger.debug(
            "teams_reply_skipped",
            reason="no_author",
            channel_id=channel_id,
            root_message_id=root_message_id,
            msg_id=msg_id,
        )
        return None

    if not msg_id:
        logger.debug(
            "teams_reply_skipped",
            reason="no_msg_id",
            channel_id=channel_id,
            root_message_id=root_message_id,
        )
        return None

    # Graph's /replies endpoint only returns replies belonging to this root thread, so
    # we trust the endpoint scoping rather than re-validating replyToId (it can differ
    # from the root id for nested quote-replies, which we still want to ingest).
    reply_to_id = msg.get("replyToId")

    return {
        "id": msg_id,
        "type": "message",
        "text": content,
        "replyToId": reply_to_id or root_message_id,
        "from": {
            "id": aad_object_id,
            "aadObjectId": aad_object_id,
            "name": user.get("displayName") or "",
        },
        "conversation": {"id": f"{channel_id};messageid={root_message_id}"},
        "channelData": {"channel": {"id": channel_id}},
        "serviceUrl": service_url,
    }
