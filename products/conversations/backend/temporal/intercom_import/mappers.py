"""Field mapping from Intercom REST API payloads to Conversations models."""

from __future__ import annotations

from products.conversations.backend.models.constants import Priority, Status

INTERCOM_STATE_MAP: dict[str, str] = {
    "open": Status.OPEN,
    "snoozed": Status.ON_HOLD,
    "closed": Status.RESOLVED,
}

INTERCOM_PRIORITY_MAP: dict[str, str | None] = {
    "none": None,
    "low": Priority.LOW,
    "medium": Priority.MEDIUM,
    "high": Priority.HIGH,
    "urgent": Priority.HIGH,
}

CUSTOMER_AUTHOR_TYPES = frozenset({"user", "lead", "contact"})


def map_intercom_state(state: str | None) -> str:
    if not state:
        return Status.OPEN
    return INTERCOM_STATE_MAP.get(state.lower(), Status.OPEN)


def map_intercom_priority(priority: str | None) -> str | None:
    if not priority:
        return None
    return INTERCOM_PRIORITY_MAP.get(priority.lower())


def map_intercom_author_type(*, author_type: str | None, part_type: str | None) -> tuple[str, bool]:
    """Return (author_type, is_private) for Comment.item_context.

    Notes are internal regardless of who wrote them. So are `unknown` parts: the API returns that
    type for parts it can't describe, and importing them as replies could show the customer
    content that was never sent to them. Contacts (users and leads) are the customer; admins, bots
    (including the AI agent) and teams are support.
    """
    if part_type and ("note" in part_type.lower() or part_type.lower() == "unknown"):
        return "support", True
    if author_type in CUSTOMER_AUTHOR_TYPES:
        return "customer", False
    return "support", False
