from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.utils.dateparse import parse_datetime

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.ai.session_batch_events_query_runner import (
    SessionBatchEventsQueryRunner,
    create_session_batch_events_query,
)
from posthog.models.comment import Comment
from posthog.models.person.util import get_persons_by_distinct_ids

from products.conversations.backend.ai.runner import SupportAgentRunner

from ee.models import Conversation

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

    from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)

MAX_CONVERSATION_CHARS = 8000
MAX_MESSAGES = 50
MAX_EVENTS_CONTEXT = 30
MAX_EXCEPTIONS_CONTEXT = 10


def _get_author_label(message: Comment) -> str:
    ctx = message.item_context or {}
    author_type = ctx.get("author_type", "customer")
    is_private = ctx.get("is_private", False)

    if author_type == "customer":
        return "Customer"
    if is_private:
        return "Support (private note)"
    return "Support"


def format_conversation(ticket: Ticket, messages: Iterable[Comment]) -> str:
    parts: list[str] = []

    current_url = None
    if ticket.session_context and isinstance(ticket.session_context, dict):
        current_url = ticket.session_context.get("current_url")

    if current_url:
        parts.append(f"The customer was on the page: {current_url}")
        parts.append("")

    parts.append("Conversation:")

    truncated: list[str] = []
    total_messages = 0
    for msg in messages:
        label = _get_author_label(msg)
        content = (msg.content or "").strip()
        if content:
            truncated.append(f"[{label}]: {content}")
            total_messages += 1

    truncated = truncated[-MAX_MESSAGES:]
    messages_truncated = total_messages > MAX_MESSAGES

    total_chars = 0
    kept: list[str] = []
    for line in reversed(truncated):
        if total_chars + len(line) > MAX_CONVERSATION_CHARS:
            break
        kept.append(line)
        total_chars += len(line)
    kept.reverse()

    if messages_truncated or len(kept) < len(truncated):
        parts.append("[Note: Earlier messages were truncated due to length limits]")
        parts.append("")

    parts.extend(kept)
    return "\n".join(parts)


def _parse_time_window(ticket_created_at: str | None) -> tuple[str, str | None]:
    """Return (after, before) for a +/-5-minute window around ticket creation."""
    if ticket_created_at:
        created_at = parse_datetime(ticket_created_at)
        if not created_at:
            created_at = datetime.fromisoformat(ticket_created_at.replace("Z", "+00:00"))
        return (created_at - timedelta(minutes=5)).isoformat(), (created_at + timedelta(minutes=5)).isoformat()
    return "-24h", None


def _fetch_session_events(team: Team, session_id: str, ticket_created_at: str | None) -> list[dict]:
    """Fetch recent events for a session from ClickHouse."""
    after, before = _parse_time_window(ticket_created_at)

    query = create_session_batch_events_query(
        session_ids=[session_id],
        select=["event", "timestamp", "properties.$current_url", "properties.$pathname"],
        events_to_ignore=["$feature_flag_called", "$pageleave", "$pageview"],
        after=after,
        before=before,
        max_total_events=MAX_EVENTS_CONTEXT,
        group_by_session=False,
    )

    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.calculate()

    events = []
    columns = response.columns or []
    for row in response.results or []:
        event_data = dict(zip(columns, row, strict=False))
        events.append(event_data)

    return events


def _fetch_session_exceptions(team: Team, session_id: str, ticket_created_at: str | None) -> list[dict]:
    """Fetch exceptions for a session from ClickHouse."""
    after, before = _parse_time_window(ticket_created_at)

    query = create_session_batch_events_query(
        session_ids=[session_id],
        select=[
            "event",
            "timestamp",
            "properties.$exception_message",
            "properties.$exception_type",
            "properties.$current_url",
        ],
        events_to_ignore=[],
        after=after,
        before=before,
        max_total_events=MAX_EXCEPTIONS_CONTEXT,
        group_by_session=False,
        event="$exception",
    )

    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.calculate()

    exceptions = []
    columns = response.columns or []
    for row in response.results or []:
        exc_data = dict(zip(columns, row, strict=False))
        exceptions.append(exc_data)

    return exceptions


def _format_enhanced_context(
    conversation_text: str,
    events: list[dict],
    exceptions: list[dict],
) -> str:
    """Format the conversation with additional technical context."""
    parts = [conversation_text]

    if exceptions:
        parts.append("\n\nRecent exceptions from the user's session:")
        for exc in exceptions[-MAX_EXCEPTIONS_CONTEXT:]:
            exc_type = exc.get("properties.$exception_type") or exc.get("$exception_type") or "Unknown"
            exc_msg = exc.get("properties.$exception_message") or exc.get("$exception_message") or "No message"
            url = exc.get("properties.$current_url") or exc.get("$current_url") or ""
            ts = exc.get("timestamp", "")
            parts.append(f"- [{ts}] {exc_type}: {exc_msg} (on {url})")

    if events:
        parts.append("\n\nRecent events from the user's session:")
        for evt in events[-MAX_EVENTS_CONTEXT:]:
            event_name = evt.get("event", "unknown")
            url = evt.get("properties.$current_url") or evt.get("$current_url") or ""
            ts = evt.get("timestamp", "")
            parts.append(f"- [{ts}] {event_name} (on {url})")

    return "\n".join(parts)


PERSON_PROPERTY_ALLOWLIST = frozenset(
    {
        "$geoip_country_name",
        "$geoip_city_name",
        "$geoip_time_zone",
        "$browser",
        "$os",
        "$initial_referrer",
        "$initial_referring_domain",
    }
)

PRIORITY_PERSON_PROPERTIES = (
    "email",
    "name",
    "first_name",
    "last_name",
    "plan",
    "company",
    "organization",
)

MAX_PERSON_PROPERTIES = 30


def _load_person_properties(team: Team, distinct_id: str) -> dict:
    try:
        persons = get_persons_by_distinct_ids(team_id=team.pk, distinct_ids=[distinct_id])
        if persons:
            return persons[0].properties or {}
    except Exception:
        capture_exception(additional_properties={"distinct_id": distinct_id})
    return {}


def _format_person_context(properties: dict) -> str:
    if not properties:
        return ""

    def _is_usable(key: str, value: object) -> bool:
        if value is None or value == "":
            return False
        if key.startswith("$") and key not in PERSON_PROPERTY_ALLOWLIST:
            return False
        return True

    filtered: dict[str, str] = {}

    for key in PRIORITY_PERSON_PROPERTIES:
        if key in properties and _is_usable(key, properties[key]):
            filtered[key] = str(properties[key])

    for key, value in properties.items():
        if len(filtered) >= MAX_PERSON_PROPERTIES:
            break
        if key in filtered:
            continue
        if not _is_usable(key, value):
            continue
        filtered[key] = str(value)

    if not filtered:
        return ""

    lines = [f"- {key}: {value}" for key, value in filtered.items()]
    return "\n".join(lines)


def _build_ticket_context(
    ticket: Ticket,
    messages: list[Comment],
    team: Team,
) -> str:
    """Build the full context string that gets injected into the agent as a ContextMessage."""
    conversation_text = format_conversation(ticket, messages)
    events: list[dict] = []
    exceptions: list[dict] = []

    if ticket.session_id:
        try:
            events = _fetch_session_events(team, ticket.session_id, ticket.created_at.isoformat())
        except Exception:
            capture_exception(additional_properties={"ticket_id": str(ticket.id)})

        try:
            exceptions = _fetch_session_exceptions(team, ticket.session_id, ticket.created_at.isoformat())
        except Exception:
            capture_exception(additional_properties={"ticket_id": str(ticket.id)})

    context = (
        _format_enhanced_context(conversation_text, events, exceptions) if events or exceptions else conversation_text
    )

    # Append person context
    person_props = _load_person_properties(team, ticket.distinct_id)
    person_text = _format_person_context(person_props)
    if person_text:
        context += f"\n\nCustomer properties:\n{person_text}"

    # Ticket metadata
    meta_parts: list[str] = []
    if ticket.channel_source:
        meta_parts.append(f"Channel: {ticket.channel_source}")
    if ticket.status:
        meta_parts.append(f"Status: {ticket.status}")
    if ticket.session_id:
        meta_parts.append(f"Session ID: {ticket.session_id}")
    if meta_parts:
        context += "\n\nTicket metadata:\n" + "\n".join(f"- {p}" for p in meta_parts)

    return context


class NoMessagesError(Exception):
    """Raised when a ticket has no messages to generate a reply for."""

    pass


def suggest_reply(
    ticket: Ticket,
    team: Team,
    user: User,
) -> str:
    """
    Generate AI-suggested reply using the support agent.

    Creates a Conversation for tracing, builds ticket context, and runs
    the SupportAgentRunner synchronously to produce a reply.

    Returns the generated reply text.
    Raises NoMessagesError if ticket has no messages.
    """
    comments = list(
        Comment.objects.filter(
            team_id=team.id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
        )
        .exclude(item_context__is_private=True)
        .order_by("created_at")
    )

    if not comments:
        raise NoMessagesError("No messages in this ticket")

    ticket_context = _build_ticket_context(ticket, comments, team)

    conversation = Conversation.objects.create(
        team=team,
        user=user,
        type=Conversation.Type.TOOL_CALL,
        title=f"Support suggestion for ticket {ticket.id}",
    )

    runner = SupportAgentRunner(
        team,
        conversation,
        user=user,
        ticket_context=ticket_context,
    )
    reply_text = runner.run()

    Comment.objects.create(
        team_id=team.id,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=reply_text,
        item_context={"author_type": "AI", "is_private": True},
    )

    return reply_text
