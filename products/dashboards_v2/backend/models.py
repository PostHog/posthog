from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class DashboardV2(TeamScopedRootMixin, UUIDModel):
    """A dashboard: one row holds the whole published JSON document in `spec`.

    The spec never names a team or project, so the same document can be copied between projects. `title`,
    `folder` and `tags` repeat values from the spec so that lists can filter and sort without reading specs.
    """

    # db_constraint=False: a real FK constraint to the hot posthog_team table
    # takes a parent lock during migration; scoping is enforced app-side.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    uid = models.CharField(max_length=63)
    spec = models.JSONField()
    version = models.PositiveIntegerField(default=1)

    title = models.CharField(max_length=300)
    # '/'-separated folder titles. "" is the top level.
    folder = models.CharField(max_length=500, blank=True, default="")
    tags = ArrayField(models.CharField(max_length=100), blank=True, default=list)

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
        db_table = "dashboards_v2_dashboard"
        constraints = [
            # A deleted dashboard frees its uid, so a project can make a new dashboard from the same document.
            models.UniqueConstraint(
                fields=["team", "uid"], condition=Q(deleted=False), name="dashboards_v2_unique_live_uid"
            ),
        ]

    def __str__(self) -> str:
        return self.title


class DashboardV2Version(TeamScopedRootMixin, UUIDModel):
    """One published spec of a dashboard. Rows are append-only: a restore publishes an old spec as a new version."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # db_index=False: the composite index below leads with dashboard_id.
    dashboard = models.ForeignKey(DashboardV2, on_delete=models.CASCADE, related_name="versions", db_index=False)
    version = models.PositiveIntegerField()
    spec = models.JSONField()
    message = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "dashboards_v2_dashboard_version"
        constraints = [
            models.UniqueConstraint(fields=["dashboard", "version"], name="dashboards_v2_unique_version"),
        ]


class DashboardV2Draft(TeamScopedRootMixin, UUIDModel):
    """An editable copy of a dashboard's spec. A dashboard can have many drafts.

    Edits arrive as JSON Patch operations, and every applied patch increments `version`, so a client can send the
    version it last saw and get a conflict instead of overwriting a newer edit. Drafts are validated permissively:
    a broken panel is stored and shown as an error, and only publishing applies the strict schema.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # db_index=False: the composite index below leads with dashboard_id.
    dashboard = models.ForeignKey(DashboardV2, on_delete=models.CASCADE, related_name="drafts", db_index=False)
    # The dashboard version this draft was copied from. If the dashboard has a newer version, publishing the draft
    # replaces the changes in that newer version.
    base_version = models.PositiveIntegerField()
    # 0 until the first edit. Drafts that nobody edited are not listed.
    version = models.PositiveIntegerField(default=0)
    spec = models.JSONField()

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    last_modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dashboards_v2_dashboard_draft"
        indexes = [
            models.Index(fields=["dashboard", "-last_modified_at"], name="dashboards_v2_draft_recency"),
        ]
