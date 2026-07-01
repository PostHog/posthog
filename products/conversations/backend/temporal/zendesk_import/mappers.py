"""Field mapping from Zendesk Support API payloads to Conversations models."""

from __future__ import annotations

from products.conversations.backend.models.constants import Channel, Priority, Status

ZENDESK_STATUS_MAP: dict[str, str] = {
    "new": Status.NEW,
    "open": Status.OPEN,
    "pending": Status.PENDING,
    "hold": Status.ON_HOLD,
    "solved": Status.RESOLVED,
    "closed": Status.RESOLVED,
}

ZENDESK_PRIORITY_MAP: dict[str, str | None] = {
    "low": Priority.LOW,
    "normal": Priority.MEDIUM,
    "high": Priority.HIGH,
    "urgent": Priority.HIGH,
}


def map_zendesk_status(status: str | None) -> str:
    if not status:
        return Status.NEW
    return ZENDESK_STATUS_MAP.get(status.lower(), Status.OPEN)


def map_zendesk_priority(priority: str | None) -> str | None:
    if not priority:
        return None
    return ZENDESK_PRIORITY_MAP.get(priority.lower())


def map_zendesk_author_type(*, role: str | None, is_public: bool) -> tuple[str, bool]:
    """Return (author_type, is_private) for Comment.item_context."""
    if not is_public:
        return "support", True
    if role in ("agent", "admin"):
        return "support", False
    return "customer", False


def default_channel_source() -> str:
    return Channel.EMAIL
