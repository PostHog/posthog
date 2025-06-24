from django.db import models

from posthog.models.organization import Organization


# DEPRECATED - do not use
class OrganizationResourceAccess(models.Model):
    class AccessLevel(models.IntegerChoices):
        """Level for which a role or user can edit or view resources"""

        CAN_ONLY_VIEW = 21, "Can only view"
        CAN_ALWAYS_EDIT = 37, "Can always edit"

    class Resources(models.TextChoices):
        FEATURE_FLAGS = "feature flags", "feature flags"
        EXPERIMENTS = "experiments", "experiments"
        COHORTS = "cohorts", "cohorts"
        DATA_MANAGEMENT = "data management", "data management"
        SESSION_RECORDINGS = "session recordings", "session recordings"
        INSIGHTS = "insights", "insights"
        DASHBOARDS = "dashboards", "dashboards"

    resource = models.CharField(max_length=32, choices=Resources.choices)
    access_level = models.PositiveSmallIntegerField(default=AccessLevel.CAN_ALWAYS_EDIT, choices=AccessLevel.choices)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="resource_access")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "resource"],
                name="unique resource per organization",
            )
        ]
