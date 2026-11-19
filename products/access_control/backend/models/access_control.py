from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDTModel


# nosemgrep: no-new-uuidt-models -- an existing model, and a new primary key default would need a migration.
class AccessControl(ModelActivityMixin, UUIDTModel):
    activity_logging_on_delete = True

    class Meta:
        app_label = "ee"
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "resource_id", "team", "organization_member", "role"],
                name="unique resource per target",
            )
        ]

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
    )

    # Configuration of what we are accessing
    access_level: models.CharField = models.CharField(max_length=32)
    resource: models.CharField = models.CharField(max_length=32)
    resource_id: models.CharField = models.CharField(max_length=36, null=True)

    # Optional scope it to a specific member
    organization_member = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
        null=True,
    )

    # Optional scope it to a specific role
    role = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="access_controls",
        related_query_name="access_controls",
        null=True,
    )

    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    # TODO: add model validation for access_level and resource
