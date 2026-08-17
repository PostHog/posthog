from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class AgentAvailability(UUIDModel):
    """Whether an agent is currently taking tickets.

    Availability rather than "out of office" because it covers a rotation as well as leave:
    an engineer on support this week is available, and unavailable the rest of the month.

    Deliberately just a flag. Moving the tickets someone already holds, or routing new ones
    around them, is a decision with a lot of team-specific shape to it, and that belongs in a
    workflow reading this state rather than in the model.

    The row persists once created, and no row means available.

    Organization-scoped because that's the granularity assignment already works at: assignees
    are validated against ``OrganizationMembership``, so being unavailable applies to every
    project in the org.
    """

    # db_constraint=False on the hot-table FKs (organization, user) so CreateModel takes no
    # lock on posthog_organization / posthog_user; app-level enforcement is enough here.
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="conversations_agent_availability",
        # The unique constraint below indexes (organization, user), so the FK's own index
        # would only duplicate its leading column.
        db_index=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    is_available = models.BooleanField(default=True, db_default=True)
    # Who last changed it — the agent themselves, an organization admin covering for them, or
    # null when a workflow or API token did it.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_agent_availability"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_agent_availability_per_org_and_user",
            ),
        ]

    def __str__(self) -> str:
        state = "available" if self.is_available else "unavailable"
        return f"{self.user} is {state} in {self.organization_id}"
