import uuid as uuidlib

from django.db import models

from .utils import sane_repr


class Organization(models.Model):
    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuidlib.uuid4, editable=False)
    members: models.ManyToManyField = models.ManyToManyField("posthog.User", through="posthog.OrganizationMembership")
    name: models.CharField = models.CharField(max_length=64)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    __repr__ = sane_repr("name")


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
    is_admin: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization_id", "user_id"]),
        ]

    def __str__(self):
        return "administrator" if self.is_admin else "member"

    __repr__ = sane_repr("organization", "user", "is_admin")
