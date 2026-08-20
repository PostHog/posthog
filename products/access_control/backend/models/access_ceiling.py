from django.db import models

from posthog.models.utils import UUIDModel


class AccessCeiling(UUIDModel):
    """An organization-wide cap on what any principal can do through one access pathway.

    Ceilings are not grants. The grants system (AccessControl rows) answers "what may this
    principal do"; a ceiling answers "how wide is this pathway", and the effective access is
    the minimum of the two. A ceiling therefore applies to every member, admins included:
    exceptions are future subject-specific ceiling rows that widen the cap, never grants.

    Absence of a row means the channel is unrestricted. `resource=None` caps every resource;
    a row naming a resource overrides the wildcard row for that resource.
    """

    class Channel(models.TextChoices):
        MCP = "mcp"

    class MaxLevel(models.TextChoices):
        # The grants vocabulary, minus levels a cap never needs. "none" disables the
        # channel; "viewer" makes it read-only.
        NONE = "none"
        VIEWER = "viewer"
        EDITOR = "editor"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "channel", "resource"],
                name="unique_ceiling_per_org_channel_resource",
                nulls_distinct=False,
            )
        ]

    # db_constraint=False: posthog_organization is a hot table, and creating a real FK
    # constraint takes a lock on it that queues behind live writes.
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="access_ceilings",
        db_constraint=False,
    )

    channel: models.CharField = models.CharField(max_length=32, choices=Channel.choices)
    # An APIScopeObject name, or None to cap every resource.
    resource: models.CharField = models.CharField(max_length=64, null=True, blank=True)
    max_level: models.CharField = models.CharField(max_length=32, choices=MaxLevel.choices)

    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        db_constraint=False,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
