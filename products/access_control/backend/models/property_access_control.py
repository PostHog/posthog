from django.db import models

from posthog.models.utils import UUIDModel


class PropertyAccessControl(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property_definition", "team", "organization_member", "role"],
                name="unique property per target",
            )
        ]

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="property_access_controls",
        related_query_name="property_access_controls",
    )

    # property selector
    property_definition = models.ForeignKey(
        "event_definitions.PropertyDefinition",
        on_delete=models.CASCADE,
        related_name="property_access_controls",
        related_query_name="property_access_controls",
        null=True,
    )

    # access rules
    access_level: models.CharField = models.CharField(max_length=32)

    # scoping rules
    organization_member = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="property_access_controls",
        related_query_name="property_access_controls",
        null=True,
    )
    role = models.ForeignKey(
        "ee.Role",
        on_delete=models.CASCADE,
        related_name="property_access_controls",
        related_query_name="property_access_controls",
        null=True,
    )

    # metadata
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
