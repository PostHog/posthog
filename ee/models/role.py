from django.db import models

from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.models.utils import UUIDModel


class Role(UUIDModel):
    name = models.CharField(max_length=200)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="roles",
        related_query_name="role",
    )
    feature_flags_access_level = models.PositiveSmallIntegerField(
        default=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        choices=OrganizationResourceAccess.AccessLevel.choices,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="roles",
        related_query_name="role",
        null=True,
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_role_name")]


class RoleMembership(UUIDModel):
    role = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="roles",
        related_query_name="role",
    )
    # TODO: Eventually remove this as we only need the organization membership
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="role_memberships",
        related_query_name="role_membership",
    )

    organization_member = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="role_memberships",
        related_query_name="role_membership",
        null=True,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "user"], name="unique_user_and_role")]
