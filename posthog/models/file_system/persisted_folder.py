from django.db import models
from django.db.models import Value
from django.db.models.expressions import F
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.file_system.constants import DEFAULT_SURFACE
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class PersistedFolder(models.Model):
    """
    Per-user, per-team persisted folder.

    A single user can have exactly one row of a given `type`
    (home, pinned, …) inside each team.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey(User, on_delete=models.CASCADE)

    TYPE_HOME = "home"
    TYPE_PINNED = "pinned"
    TYPE_CUSTOM_PRODUCTS = "custom_products"
    type: models.CharField = models.CharField(
        max_length=32,
        choices=[
            (TYPE_HOME, "Home"),
            (TYPE_PINNED, "Pinned"),
            (TYPE_CUSTOM_PRODUCTS, "Custom Products"),
        ],
    )

    protocol: models.CharField = models.CharField(max_length=64, default="products://")
    path: models.TextField = models.TextField(blank=True, default="")

    # Product surface this folder belongs to (e.g. "web", "desktop"). NULL == DEFAULT_SURFACE.
    # Unlike FileSystem items, a folder `type` (home, pinned, …) is NOT surface-exclusive — each
    # surface has its own "home" — so surface is part of the uniqueness below. The constraint
    # coalesces NULL to the default surface, matching the NULL == "web" rule used for reads, so a
    # legacy NULL row and an explicit "web" row can never both exist for the same (team, user, type).
    surface: models.CharField = models.CharField(max_length=100, null=True, blank=True)

    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, editable=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                F("team_id"),
                F("user_id"),
                F("type"),
                Coalesce(F("surface"), Value(DEFAULT_SURFACE)),
                name="posthog_pf_team_user_type_surface_uniq",
            ),
        ]
        indexes = [
            models.Index(F("team_id"), F("user_id"), name="posthog_pf_team_user"),
            models.Index(F("team_id"), F("user_id"), F("type"), name="posthog_pf_team_user_type"),
        ]
        verbose_name = "Persisted Folder"
        verbose_name_plural = "Persisted Folders"

    def __str__(self) -> str:
        return f"{self.team_id}:{self.user_id}:{self.type} → {self.protocol}{self.path}"
