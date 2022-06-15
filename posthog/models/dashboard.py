from typing import Any, Dict, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_deprecate_fields import deprecate_field

from posthog.constants import AvailableFeature
from posthog.utils import absolute_uri


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
        default=RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT, choices=RestrictionLevel.choices,
    )
    insights = models.ManyToManyField("posthog.Insight", related_name="dashboards", through="DashboardTile", blank=True)

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), blank=True, default=list), return_instead=[],
    )
    tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), blank=True, default=None), return_instead=[],
    )

    @property
    def url(self):
        return absolute_uri(f"/dashboard/{self.id}")

    @property
    def effective_restriction_level(self) -> RestrictionLevel:
        return (
            self.restriction_level
            if self.team.organization.is_feature_available(AvailableFeature.DASHBOARD_PERMISSIONING)
            else self.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def get_effective_privilege_level(self, user_id: int) -> PrivilegeLevel:
        if (
            # Checks can be skipped if the dashboard in on the lowest restriction level
            self.effective_restriction_level == self.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
            # Users with restriction rights can do anything
            or self.can_user_restrict(user_id)
        ):
            # Returning the highest access level if no checks needed
            return self.PrivilegeLevel.CAN_EDIT
        from ee.models import DashboardPrivilege

        try:
            return cast(Dashboard.PrivilegeLevel, self.privileges.values_list("level", flat=True).get(user_id=user_id))
        except DashboardPrivilege.DoesNotExist:
            # Returning the lowest access level if there's no explicit privilege for this user
            return self.PrivilegeLevel.CAN_VIEW

    def can_user_edit(self, user_id: int) -> bool:
        if self.effective_restriction_level < self.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT:
            return True
        return self.get_effective_privilege_level(user_id) >= self.PrivilegeLevel.CAN_EDIT

    def can_user_restrict(self, user_id: int) -> bool:
        # Sync conditions with frontend hasInherentRestrictionsRights
        from posthog.models.organization import OrganizationMembership

        # The owner (aka creator) has full permissions
        if user_id == self.created_by_id:
            return True
        effective_project_membership_level = self.team.get_effective_membership_level(user_id)
        return (
            effective_project_membership_level is not None
            and effective_project_membership_level >= OrganizationMembership.Level.ADMIN
        )

    def get_analytics_metadata(self) -> Dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "pinned": self.pinned,
            "item_count": self.insights.count(),
            "is_shared": self.is_shared,
            "created_at": self.created_at,
            "has_description": self.description != "",
            "tags_count": self.tagged_items.count(),
        }
