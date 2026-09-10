from django.db import models
from django.db.models import F, Q

from posthog.models.utils import UUIDTModel

from products.access_control.backend.models.organization_resource_access import OrganizationResourceAccess


class Role(UUIDTModel):
    class Meta:
        app_label = "ee"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_role_name")]

    name = models.CharField(max_length=200)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="roles",
        related_query_name="role",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="roles",
        related_query_name="role",
        null=True,
    )

    # DEPRECATED - do not use
    feature_flags_access_level = models.PositiveSmallIntegerField(
        default=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        choices=OrganizationResourceAccess.AccessLevel,
    )

    members = models.ManyToManyField(
        "posthog.User",
        through="ee.RoleMembership",
    )


class RoleMembershipQuerySet(models.QuerySet["RoleMembership"]):
    def valid_for_authorization(self) -> "RoleMembershipQuerySet":
        return self.filter(
            Q(organization_member__isnull=True) | Q(organization_member__organization_id=F("role__organization_id"))
        )


class RoleMembership(UUIDTModel):
    objects = RoleMembershipQuerySet.as_manager()

    class Meta:
        app_label = "ee"
        constraints = [models.UniqueConstraint(fields=["role", "user"], name="unique_user_and_role")]

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
