import uuid as uuidlib
from typing import Tuple

from django.db import models

from .utils import sane_repr


class Organization(models.Model):
    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuidlib.uuid4, editable=False)
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


class MembershipLevel(IntEnum):
    MEMBER = 0
    ADMIN = 1

    def __str__(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        return {self.MEMBER: "member", self.ADMIN: "administrator",}[self]

    @classmethod
    def as_choices(cls) -> Tuple[Tuple[str, str]]:
        return tuple((level.value, level.label) for level in cls)


class OrganizationMembership(models.Model):
    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuidlib.uuid4, editable=False)
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="memberships", related_query_name="membership",
    )
    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        related_query_name="organization_membership",
    )
    level: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=MembershipLevel.MEMBER, choices=MembershipLevel.as_choices()
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization_id", "user_id"]),
        ]

    def __str__(self):
        return "administrator" if self.is_admin else "member"

    __repr__ = sane_repr("organization", "user", "is_admin")
