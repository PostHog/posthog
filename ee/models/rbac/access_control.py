from django.db import models

from posthog.models.organization import Organization


class AccessControl(models.Model):
    organization: models.ForeignKey = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="access_control"
    )

    # Configuration of what we are accessing
    resource: models.CharField = models.CharField(max_length=32)
    resource_id: models.CharField = models.CharField(max_length=36)
    access_level: models.CharField = models.CharField(max_length=32)

    # Optional which organization membership does this apply to
    organization_membership: models.ForeignKey = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="access_control",
        related_query_name="access_control",
        null=True,
    )

    # Optional which role does this apply to?
    role: models.ForeignKey = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="access_control",
        related_query_name="access_control",
        null=True,
    )

    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "resource", "user", "role"],
                name="unique resource per organization",
            )
        ]
