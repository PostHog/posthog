from django.db import models

from posthog.models.utils import UUIDTModel


class AccessControlManager(models.TextChoices):
    """External system that owns a rule. A rule with no manager is owned by whoever edits it."""

    TERRAFORM = "terraform", "Terraform"


class AccessControl(UUIDTModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "resource_id", "team", "organization_member", "role"],
                name="unique resource per target",
            )
        ]
        indexes = [
            # Backs the per-team "does any rule have a manager?" check, which runs on every
            # access control page load. Partial, because managed rules are the rare case.
            models.Index(
                fields=["team"],
                condition=models.Q(managed_by__isnull=False),
                name="access_control_managed_by_team",
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

    # Set when an external system writes or claims the rule. This is drift protection, not a
    # security boundary: it is derived from the caller's user agent, which an API client can set
    # freely. It does hold against the web app, because a browser will not let a page override
    # its own user agent.
    managed_by = models.CharField(max_length=32, choices=AccessControlManager, null=True, blank=True)
    # Refreshed every time the manager claims the rule. A claim that stops arriving is the signal
    # that the rule was orphaned - the manager dropped it without telling us.
    managed_at = models.DateTimeField(null=True, blank=True)

    # TODO: add model validation for access_level and resource
