from typing import TYPE_CHECKING, Any, Dict

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
        INHERENT_VIEW_AND_EDIT = 21, "Everyone in the project can edit"
        INHERENT_VIEW_BUT_EXPLICIT_EDIT = 37, "Only those invited to this dashboard can edit"

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
        default=RestrictionLevel.INHERENT_VIEW_AND_EDIT, choices=RestrictionLevel.choices
    )
    tags: ArrayField = ArrayField(models.CharField(max_length=32), blank=True, default=list)

    def get_effective_privilege_level(self, user: "User") -> RestrictionLevel:
        if (
            # If we're on the lowest restriction level, there's no need for further checks
            self.restriction_level == self.RestrictionLevel.INHERENT_VIEW_AND_EDIT
            # Otherwise there is a need for further checks IF dashboard permissioning is available to this org
            or not self.team.organization.is_feature_available(AvailableFeature.PROJECT_BASED_PERMISSIONING)
        ):
            # Returning the highest access level if no checks needed
            return self.RestrictionLevel.INHERENT_VIEW_BUT_EXPLICIT_EDIT
        from ee.models import DashboardPrivilege

        try:
            return self.privileges.values_list("level", flat=True).get(user=user)
        except DashboardPrivilege.DoesNotExist:
            # Returning the lowest access level if there's no explicit privilege for this user
            return self.RestrictionLevel.INHERENT_VIEW_AND_EDIT

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
