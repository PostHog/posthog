"""Reading and changing whether agents are taking tickets.

An unavailable agent can't be handed a ticket. Nothing else follows from it on its own: what
should happen to the work they already hold is a routing decision, and routing is what workflows
are for. This is only the state a workflow reads and writes.
"""

from __future__ import annotations

from django.db import transaction

from posthog.models.organization import Organization
from posthog.models.user import User

from products.conversations.backend.models import AgentAvailability


def is_available(organization_id: str, user_id: int) -> bool:
    """Whether this agent is taking tickets. No row means available."""
    return not AgentAvailability.objects.filter(
        organization_id=organization_id, user_id=user_id, is_available=False
    ).exists()


def set_availability(
    *,
    organization: Organization,
    target_user_id: int,
    actor: User | None,
    is_available: bool,
) -> bool:
    """Change an agent's availability. Returns whether it actually changed."""
    with transaction.atomic():
        # Land the row in the neutral available state first so a double-click races on the
        # unique constraint here, where get_or_create handles it, rather than on the update.
        availability, _ = AgentAvailability.objects.get_or_create(
            organization=organization,
            user_id=target_user_id,
            defaults={"is_available": True},
        )
        availability = AgentAvailability.objects.select_for_update().get(pk=availability.pk)

        was_available = availability.is_available
        availability.is_available = is_available
        availability.changed_by = actor
        availability.save(update_fields=["is_available", "changed_by", "updated_at"])

    return was_available != is_available
