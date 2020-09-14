import uuid as uuidlib
from enum import IntEnum
from multiprocessing import Value
from typing import Any, Optional, Tuple

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
    joined_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization_id", "user_id"], name="unique_organization_membership")
        ]

    def __str__(self):
        return str(self.Level(self.level))

    __repr__ = sane_repr("organization", "user", "level")


class OrganizationInvite(UUIDModel):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="invites", related_query_name="invite"
    )
    uses: models.PositiveIntegerField = models.PositiveIntegerField(default=0)
    max_uses: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True, default=None)
    target_email: models.EmailField = models.EmailField(null=True, blank=True, default=None, db_index=True)
    last_used_by: models.ForeignKey = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, related_name="+", null=True,
    )
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

    def validate(self, user: Optional[Any] = None) -> None:
        if self.max_uses is not None and self.uses >= self.max_uses:
            raise ValueError("Uses limit used up.")
        if (
            user is not None
            and OrganizationMembership.objects.filter(organization=self.organization, user=user).exists()
        ):
            raise ValueError("User already is a member of the organization.")
        if self.target_email:
            if user is not None and self.target_email != user.email:
                raise ValueError("User's email differs from the one the invite is for.")
            if OrganizationMembership.objects.filter(
                organization=self.organization, user__email=self.target_email
            ).exists():
                raise ValueError("Target email already is a member of the organization.")

    def use(self, user: Any, *, validate: bool = False):
        if validate:
            self.validate(user)
        self.organization.members.add(user)
        save_user = False
        if user.current_organization is None:
            user.current_organization = self.organization
            save_user = True
        if user.current_team is None:
            user.current_team = user.current_organization.teams.first()
            save_user = True
        if save_user:
            user.save()
        self.last_used_by = user
        self.uses += 1
        self.save()

    def __str__(self):
        return f"{settings.SITE_URL}/signup/{self.id}/"

    __repr__ = sane_repr("organization", "target_email", "created_by")


@receiver(models.signals.pre_delete, sender=OrganizationMembership)
def ensure_organization_membership_consistency(sender, instance: OrganizationMembership, **kwargs):
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
