from django.db import models

from posthog.models.utils import UUIDModel


class SurfaceAccessLimit(UUIDModel):
    """An organization-wide cap on what any principal can do through one access surface.
    Example surfaces: the MCP server, a personal API key, a public share link.

    A limit is not a grant. AccessControl rows answer "what may this principal do". A limit
    answers "how much this surface allows". The effective access is the minimum of the two.
    A limit applies to every member, including admins. Only a future subject-specific limit
    row can widen a limit. A grant cannot.

    No row means the surface has no limit. A row with `resource=None` limits every resource.
    A row that names a resource overrides the wildcard row for that resource.
    """

    class Surface(models.TextChoices):
        MCP = "mcp"

    class MaxLevel(models.TextChoices):
        # The grants vocabulary without the levels a limit never needs. "none" disables
        # the surface. "viewer" makes it read-only.
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

    # db_constraint=False because posthog_organization is a hot table. A real FK
    # constraint takes a lock on it, and that lock queues behind live writes.
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
