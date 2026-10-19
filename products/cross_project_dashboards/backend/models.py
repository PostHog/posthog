"""
Django models for cross_project_dashboards.

These models are organization-scoped, not team-scoped, so they do not use
`TeamScopedRootMixin`. A cross-project dashboard spans several projects by design, so scoping
its reads to one team would break it. `check-idor-model-coverage.py` classifies a model with
an `organization` FK and no `team` FK as org_scoped.

Keep models thin — business logic belongs in logic/.
"""

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel, sane_repr


class CrossProjectDashboard(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A dashboard the organization owns, holding insights from several projects."""

    # Keys to hot parent tables carry no database constraint, so creating this table takes no lock
    # on them, and no reverse accessor, so this product adds nothing to the parent classes.
    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="+", db_constraint=False
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(default=dict, blank=True)

    __repr__ = sane_repr("id", "organization_id", "name")

    class Meta:
        indexes = [models.Index(fields=["organization", "deleted"], name="cpd_org_deleted_idx")]

    def __str__(self) -> str:
        return self.name


class CrossProjectDashboardTile(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One insight from one project, placed on a cross-project dashboard.

    `project_id` and `insight_id` are plain integers, not foreign keys. A foreign key cascades,
    so deleting a project would delete the tile and leave no trace of what was there. Plain
    integers let the tile survive and report that its source is gone.

    The column is `project_id`, never `team_id`. `check-idor-model-coverage.py` treats a non-FK
    `team_id` column as team-scoped, which would require a manager that scopes reads to one team.
    """

    dashboard = models.ForeignKey(CrossProjectDashboard, on_delete=models.CASCADE, related_name="tiles")
    # Denormalized from the dashboard so this table classifies as org-scoped on its own.
    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="+", db_constraint=False
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    project_id = models.BigIntegerField()
    insight_id = models.BigIntegerField()
    layouts = models.JSONField(default=dict, blank=True)
    color = models.CharField(max_length=400, null=True, blank=True)
    filters_overrides = models.JSONField(default=dict, blank=True)
    deleted = models.BooleanField(default=False)

    __repr__ = sane_repr("id", "dashboard_id", "project_id", "insight_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dashboard", "project_id", "insight_id"],
                condition=models.Q(deleted=False),
                name="unique_live_tile_per_dashboard_insight",
            )
        ]
        indexes = [models.Index(fields=["dashboard", "deleted"], name="cpd_tile_dash_deleted_idx")]

    def __str__(self) -> str:
        return f"insight {self.insight_id} from project {self.project_id}"
