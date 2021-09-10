from typing import Optional

from django.db import models
from rest_framework import exceptions

from posthog.models import OrganizationMembership
from posthog.models.utils import UUIDModel, sane_repr


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
    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
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
            models.UniqueConstraint(fields=["team_id", "user_id"], name="unique_team_membership"),
        ]

    def __str__(self):
        return str(self.Level(self.level))

    def validate_update(
        self, membership_being_updated: "ExplicitTeamMembership", new_level: Optional[Level] = None
    ) -> None:
        try:
            my_parent_membership: OrganizationMembership = OrganizationMembership.objects.get(
                user_id=self.user_id, organization_id=self.team.organization_id
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.ValidationError("You don't belong to the organization anymore.")
        my_real_level = max(my_parent_membership.level, self.level)
        if new_level is not None:
            if membership_being_updated.id == self.id:
                raise exceptions.PermissionDenied("You can't change your own access level.")
            elif new_level > my_real_level:
                raise exceptions.PermissionDenied(
                    "You can only change access level of others to lower or equal to your current one."
                )
        if membership_being_updated.id != self.id:
            if membership_being_updated.team.organization_id != self.team.organization_id:
                raise exceptions.PermissionDenied("You both need to belong to the same organization.")
            if my_real_level < ExplicitTeamMembership.Level.ADMIN:
                raise exceptions.PermissionDenied("You can only edit others if you are an admin.")
            if membership_being_updated.level > my_real_level:
                raise exceptions.PermissionDenied("You can only edit others with level lower or equal to you.")

    __repr__ = sane_repr("team", "user", "level")
