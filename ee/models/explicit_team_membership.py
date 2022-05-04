from typing import TYPE_CHECKING

from django.db import models

from posthog.models.utils import UUIDModel, sane_repr

if TYPE_CHECKING:
    from posthog.models.organization import OrganizationMembership


# We call models that grant a user access to some grouping of users a "membership"
class ExplicitTeamMembership(UUIDModel):
    class Level(models.IntegerChoices):
        """Keep in sync with OrganizationMembership.Level (only difference being organizations having an Owner)."""

        MEMBER = 1, "member"
        ADMIN = 8, "administrator"

    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="explicit_memberships",
        related_query_name="explicit_membership",
    )
    parent_membership: models.ForeignKey = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="explicit_team_memberships",
        related_query_name="explicit_team_membership",
    )
    level: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=Level.MEMBER, choices=Level.choices
    )
    joined_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "parent_membership"], name="unique_explicit_team_membership"),
        ]

    def __str__(self):
        return str(self.Level(self.level))

    @property
    def effective_level(self) -> "OrganizationMembership.Level":
        """If organization level is higher than project level, then that takes precedence over explicit project level.
        """
        return max(self.level, self.parent_membership.level)

    __repr__ = sane_repr("team", "parent_membership", "level")
