"""Field mapping from Pylon REST API payloads to Conversations models."""

from __future__ import annotations

from collections.abc import Mapping

from products.conversations.backend.models.constants import Priority, Status

PYLON_STATE_MAP: dict[str, str] = {
    "new": Status.NEW,
    "waiting_on_you": Status.OPEN,
    "waiting_on_customer": Status.PENDING,
    "on_hold": Status.ON_HOLD,
    "closed": Status.RESOLVED,
}

PYLON_PRIORITY_MAP: dict[str, str | None] = {
    "low": Priority.LOW,
    "medium": Priority.MEDIUM,
    "high": Priority.HIGH,
    "urgent": Priority.HIGH,
}


def is_standard_pylon_state(state: str | None) -> bool:
    return not state or state.lower() in PYLON_STATE_MAP


def map_pylon_state(state: str | None, custom_status_categories: Mapping[str, str] | None = None) -> str:
    """Map an issue state to a ticket status.

    A workspace can define custom statuses, and Pylon gives each one a category.
    `custom_status_categories` maps a custom slug to that category, and a category that names a
    standard state resolves through it. Any other state imports as open, so the ticket stays
    visible in the inbox.
    """
    if not state:
        return Status.OPEN
    slug = state.lower()
    if slug in PYLON_STATE_MAP:
        return PYLON_STATE_MAP[slug]
    category = (custom_status_categories or {}).get(slug, "")
    return PYLON_STATE_MAP.get(category.lower(), Status.OPEN)


def map_pylon_priority(priority: str | None) -> str | None:
    if not priority:
        return None
    return PYLON_PRIORITY_MAP.get(priority.lower())


def map_pylon_author_type(*, is_private: bool, is_contact: bool) -> tuple[str, bool]:
    """Return (author_type, is_private) for Comment.item_context.

    Internal notes are private regardless of who wrote them. A contact is the customer. Every
    other author is support: a teammate, or a bot or automation, which has neither a contact nor
    a user.
    """
    if is_private:
        return "support", True
    if is_contact:
        return "customer", False
    return "support", False
