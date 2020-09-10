import uuid as uuidlib
from enum import IntEnum
from typing import Tuple

from django.conf import settings
from django.db import models
from django.dispatch import receiver

from .utils import UUIDModel, sane_repr


class Organization(UUIDModel):
    members: models.ManyToManyField = models.ManyToManyField(
        "posthog.User",
        through="posthog.OrganizationMembership",
        related_name="organizations",
        related_query_name="organization",
    )
    name: models.CharField = models.CharField(max_length=64)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    __repr__ = sane_repr("name")


class OrganizationMembership(UUIDModel):
    class Level(models.IntegerChoices):
        MEMBER = 1, "member"
        ADMIN = 8, "administrator"

    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="memberships", related_query_name="membership"
    )
    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        related_query_name="organization_membership",
    )
    level: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=Level.MEMBER, choices=Level.choices
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization_id", "user_id"], name="unique_organization_membership")
        ]

    def __str__(self):
        return str(self.Level(self.level))

    __repr__ = sane_repr("organization", "user", "is_admin")


class OrganizationInvite(UUIDModel):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="invites", related_query_name="invite"
    )
    uses: models.PositiveIntegerField = models.PositiveIntegerField(default=0)
    max_uses: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True, default=None)
    target_email: models.EmailField = models.EmailField(null=True, blank=True, default=None, db_index=True)
    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="organization_invites",
        related_query_name="organization_invite",
        null=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(uses__lte=models.F("max_uses")), name="max_uses_respected")
        ]

    @property
    def is_usable(self) -> bool:
        if self.uses >= self.max_uses:
            # uses depleted
            return False
        if (
            self.target_email
            and OrganizationMembership.objects.filter(
                organization=self.organization, user__email=self.target_email
            ).exists()
        ):
            # target_email has joined organization already
            return False
        return True

    def __str__(self):
        return f"{settings.SITE_URL}/signup/{self.id}/"

    __repr__ = sane_repr("organization", "target_email", "created_by")


@receiver(models.signals.m2m_changed, sender=Organization.members.through)
def ensure_organization_membership_consistency(sender, instance: OrganizationMembership, action: str, **kwargs):
    if action == "pre_remove":
        save_user = False
        if instance.user.current_organization == instance.organization:
            # reset current_organization if it's the removed organization
            instance.user.current_organization = None
            save_user = True
        if instance.user.current_team is not None and instance.user.current_team.organization == instance.organization:
            # reset current_team if it belongs to the removed organization
            instance.user.current_team = None
            save_user = True
        if save_user:
            instance.user.save()
