from django.db import models

from posthog.models.organization import Organization


# TODO: Should this be a uuidmodel - we don't need the ID
class AccessControl(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "resource", "resource_id", "team", "organization_membership", "role"],
                name="unique resource per target",
            )
        ]

    organization: models.ForeignKey = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="access_controls"
    )

    # Configuration of what we are accessing
    resource: models.CharField = models.CharField(max_length=32)
    access_level: models.CharField = models.CharField(max_length=32)
    resource_id: models.CharField = models.CharField(max_length=36, null=True)

    # Optional scoping of the resource to a specific team
    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
        null=True,
    )

    # Optional which organization membership does this apply to
    organization_membership: models.ForeignKey = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
        null=True,
    )

    # Optional which role does this apply to
    role: models.ForeignKey = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
        null=True,
    )

    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
