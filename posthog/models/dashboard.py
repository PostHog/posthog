from typing import TYPE_CHECKING, Any, Dict, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.constants import AvailableFeature

if TYPE_CHECKING:
    from posthog.models.user import User


class Dashboard(models.Model):
    class CreationMode(models.TextChoices):
        DEFAULT = "default", "Default"
        TEMPLATE = "template", "Template"  # dashboard was created from a predefined template
        DUPLICATE = "duplicate", "Duplicate"  # dashboard was duplicated from another dashboard

    class RestrictionLevel(models.IntegerChoices):
        """Collaboration restriction level (which is a dashboard setting). Sync with PrivilegeLevel."""

        EVERYONE_IN_PROJECT_CAN_EDIT = 21, "Everyone in the project can edit"
        ONLY_COLLABORATORS_CAN_EDIT = 37, "Only those invited to this dashboard can edit"

    class PrivilegeLevel(models.IntegerChoices):
        """Collaboration privilege level (which is a user property). Sync with RestrictionLevel."""

        CAN_VIEW = 21, "Can view dashboard"
        CAN_EDIT = 37, "Can edit dashboard"

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.TextField = models.TextField(blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    share_token: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    is_shared: models.BooleanField = models.BooleanField(default=False)
    last_accessed_at: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    filters: models.JSONField = models.JSONField(default=dict)
    creation_mode: models.CharField = models.CharField(max_length=16, default="default", choices=CreationMode.choices)
    restriction_level: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        default=RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT, choices=RestrictionLevel.choices
    )
    tags: ArrayField = ArrayField(models.CharField(max_length=32), blank=True, default=list)

    def get_effective_privilege_level(self, user: "User") -> PrivilegeLevel:
        if (
            # There is a need for  checks IF dashboard permissioning is available to this org
            not self.team.organization.is_feature_available(AvailableFeature.PROJECT_BASED_PERMISSIONING)
            # Checks can be skipped if the dashboard in on the lowest restriction level
            or self.restriction_level == self.PrivilegeLevel.CAN_VIEW
            # Users with inherent restriction rights can do anything
            or self.does_user_have_inherent_restriction_rights(user)
        ):
            # Returning the highest access level if no checks needed
            return self.PrivilegeLevel.CAN_EDIT
        from ee.models import DashboardPrivilege

        try:
            return cast(Dashboard.PrivilegeLevel, self.privileges.values_list("level", flat=True).get(user=user))
        except DashboardPrivilege.DoesNotExist:
            # Returning the lowest access level if there's no explicit privilege for this user
            return self.PrivilegeLevel.CAN_VIEW

    def can_user_edit(self, user: "User") -> bool:
        if self.restriction_level < self.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT:
            return True
        return self.get_effective_privilege_level(user) >= self.PrivilegeLevel.CAN_EDIT

    def does_user_have_inherent_restriction_rights(self, user: "User") -> bool:
        from posthog.models.organization import OrganizationMembership

        return (
            # The owner (aka creator) has full permissions
            user.id == self.created_by_id
            # Project admins get full permissions as well
            or self.team.get_effective_membership_level(user) >= OrganizationMembership.Level.ADMIN
        )

    def get_analytics_metadata(self) -> Dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "pinned": self.pinned,
            "item_count": self.items.count(),
            "is_shared": self.is_shared,
            "created_at": self.created_at,
            "has_description": self.description != "",
            "tags_count": len(self.tags),
        }
