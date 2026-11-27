from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id

from products.dashboards.backend.facade.enums import BoardManagedBy


class DashboardV2Board(TeamScopedRootMixin, UUIDModel):
    """A `dashboard-v2` board: one row holds the whole document in `spec`, as a notebook holds its content.

    The document never names a project; the row's team does. `title`, `tags` and `folder` repeat values from the
    document so lists can filter and sort without reading it, and nothing queries inside `spec`.
    `version` counts saves for optimistic concurrency. It is not the document's own schema version, which is
    `spec["version"]`.
    """

    # db_constraint=False: a real foreign key to posthog_team or posthog_user locks the parent while
    # the migration runs. Scoping is enforced by the team-scoped manager.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    uid = models.CharField(max_length=12, default=generate_short_id)
    spec = models.JSONField()
    version = models.PositiveIntegerField(default=1)

    title = models.CharField(max_length=400)
    tags = ArrayField(models.CharField(max_length=100), blank=True, default=list)
    # '/'-separated folder titles. "" is the top level.
    folder = models.CharField(max_length=500, blank=True, default="")

    managed_by = models.CharField(max_length=20, choices=BoardManagedBy.choices, default=BoardManagedBy.NATIVE.value)
    # The template the board was made from, so it can later be offered that template's newer versions.
    template_id = models.CharField(max_length=200, null=True, blank=True)
    template_version = models.PositiveIntegerField(null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    last_modified_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "dashboards_v2_board"
        constraints = [
            models.UniqueConstraint(fields=["team", "uid"], condition=Q(deleted=False), name="dashboards_v2_board_uid"),
        ]
        indexes = [
            models.Index(fields=["team", "-last_modified_at"], name="dashboards_v2_board_recency"),
        ]

    def __str__(self) -> str:
        return self.title
