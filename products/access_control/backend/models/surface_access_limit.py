from django.db import models

from posthog.models.utils import UUIDModel


class SurfaceAccessLimit(UUIDModel):
    """An organization-wide cap on what any principal can do through one access surface, such as
    the MCP server, a personal API key, or a public share link.

    Limits are not grants. The grants system (AccessControl rows) answers "what may this
    principal do"; a limit answers "how much this surface allows", and the effective access is
    the minimum of the two. A limit therefore applies to every member, admins included:
    exceptions are future subject-specific limit rows that widen it, never grants.

    Absence of a row means the surface is unrestricted. `resource=None` limits every resource;
    a row naming a resource overrides the wildcard row for that resource.
    """

    class Surface(models.TextChoices):
        MCP = "mcp"

    class MaxLevel(models.TextChoices):
        # The grants vocabulary, minus levels a limit never needs. "none" disables the
        # surface; "viewer" makes it read-only.
        NONE = "none"
        VIEWER = "viewer"
        EDITOR = "editor"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "surface", "resource"],
                name="unique_limit_per_org_surface_resource",
                nulls_distinct=False,
            )
        ]

    # db_constraint=False: posthog_organization is a hot table, and creating a real FK
    # constraint takes a lock on it that queues behind live writes.
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="surface_access_limits",
        db_constraint=False,
    )

    surface: models.CharField = models.CharField(max_length=32, choices=Surface.choices)
    # An APIScopeObject name, or None to limit every resource.
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
