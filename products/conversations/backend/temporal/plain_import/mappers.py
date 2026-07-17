"""Field mapping from Plain GraphQL payloads to Conversations models."""

from __future__ import annotations

from typing import Any

from products.conversations.backend.models.constants import Channel, Priority, Status

PLAIN_STATUS_MAP: dict[str, str] = {
    "TODO": Status.OPEN,
    "SNOOZED": Status.ON_HOLD,
    "DONE": Status.RESOLVED,
}

# Plain priority: 0 = urgent, 1 = high, 2 = normal, 3 = low — collapse to PostHog's 3 levels.
PLAIN_PRIORITY_MAP: dict[int, str] = {
    0: Priority.HIGH,
    1: Priority.HIGH,
    2: Priority.MEDIUM,
    3: Priority.LOW,
}

PLAIN_MESSAGE_SOURCE_CHANNEL_MAP: dict[str, str] = {
    "EMAIL": Channel.EMAIL,
    "CHAT": Channel.WIDGET,
    "API": Channel.EMAIL,
    "SLACK": Channel.SLACK,
    "MS_TEAMS": Channel.TEAMS,
    "DISCORD": Channel.WIDGET,
    "INTERNAL": Channel.EMAIL,
}

CUSTOMER_ACTOR_TYPENAMES = frozenset({"CustomerActor", "DeletedCustomerActor"})
SUPPORT_ACTOR_TYPENAMES = frozenset({"UserActor", "MachineUserActor", "SystemActor"})


def map_plain_status(status: str | None) -> str:
    if not status:
        return Status.NEW
    return PLAIN_STATUS_MAP.get(status.upper(), Status.OPEN)


def map_plain_priority(priority: int | None) -> str | None:
    if priority is None:
        return None
    return PLAIN_PRIORITY_MAP.get(priority)


def map_plain_channel_source(message_source: str | None) -> str:
    if not message_source:
        return Channel.EMAIL
    return PLAIN_MESSAGE_SOURCE_CHANNEL_MAP.get(message_source.upper(), Channel.EMAIL)


def map_plain_author_type(*, actor_typename: str | None, entry_typename: str | None) -> tuple[str, bool]:
    """Return (author_type, is_private) for Comment.item_context.

    Notes are always private support comments. Otherwise classify by actor:
    CustomerActor → customer; User/MachineUser/System → support.
    """
    if entry_typename == "NoteEntry":
        return "support", True
    if actor_typename in CUSTOMER_ACTOR_TYPENAMES:
        return "customer", False
    if actor_typename in SUPPORT_ACTOR_TYPENAMES:
        return "support", False
    # Unknown actor — treat as support so we don't attribute staff content to the customer.
    return "support", False


def _custom_entry_body(components: list[dict[str, Any]] | None) -> str:
    if not components:
        return ""
    parts: list[str] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            typename = node.get("__typename")
            if typename == "ComponentText" and node.get("text"):
                parts.append(str(node["text"]))
            elif typename == "ComponentPlainText" and node.get("plainText"):
                parts.append(str(node["plainText"]))
            row_main = node.get("rowMainContent")
            if isinstance(row_main, list):
                walk(row_main)
            container = node.get("containerContent")
            if isinstance(container, list):
                walk(container)

    walk(components)
    return "\n".join(parts).strip()


def extract_entry_body(entry: dict[str, Any]) -> str:
    """Pull the best available text body from a Plain timeline entry payload."""
    typename = entry.get("__typename")
    if typename == "EmailEntry":
        body = (entry.get("fullMarkdownContent") or entry.get("fullTextContent") or "").strip()
        subject = (entry.get("subject") or "").strip()
        if subject and body:
            return f"{subject}\n\n{body}"
        return subject or body
    if typename == "NoteEntry":
        return (entry.get("markdown") or entry.get("text") or "").strip()
    if typename in (
        "ChatEntry",
        "SlackMessageEntry",
        "SlackReplyEntry",
        "MSTeamsMessageEntry",
    ):
        return (entry.get("text") or entry.get("markdownContent") or "").strip()
    if typename == "DiscordMessageEntry":
        return (entry.get("markdownContent") or "").strip()
    if typename == "CustomEntry":
        title = (entry.get("title") or "").strip()
        body = _custom_entry_body(entry.get("components"))
        if title and body:
            return f"{title}\n\n{body}"
        return title or body
    return ""


def extract_entry_attachments(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return Attachment nodes from a message-bearing entry, if any."""
    attachments = entry.get("attachments")
    if not isinstance(attachments, list):
        return []
    return [a for a in attachments if isinstance(a, dict) and a.get("id")]


def extract_entry_author(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort (name, email) for the entry author from EmailEntry from/to fields."""
    if entry.get("__typename") != "EmailEntry":
        return None, None
    from_participant = entry.get("from") or {}
    if not isinstance(from_participant, dict):
        return None, None
    name = (from_participant.get("name") or "").strip() or None
    email = (from_participant.get("email") or "").strip() or None
    return name, email
