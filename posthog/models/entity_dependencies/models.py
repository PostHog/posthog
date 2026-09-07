from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EntityDependency(TeamScopedRootMixin, UUIDModel):
    """A recorded reference from one entity (the source) to another (the target).

    Rows are derived data: `sync_dependencies` recomputes the full set for a source from the
    source instance and diffs it against what is stored, so any row can be rebuilt at any time.
    Entity types are stable string keys owned by the registry, not content types, so a model
    moving between apps does not invalidate stored rows. Ids are stored as strings because
    sources and targets mix UUID and integer primary keys.
    """

    # db_constraint=False: posthog_team is a hot table; a real FK constraint would lock it on
    # CREATE TABLE. Tenant isolation is enforced by the fail-closed TeamScopedManager, not the DB FK.
    # db_index=False: both composite indexes below lead with team_id, so a separate index is redundant.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)

    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    role = models.CharField(max_length=64)
    path = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_type", "source_id", "target_type", "target_id", "role", "path"],
                name="unique_entity_dependency",
            )
        ]
        indexes = [
            # "What references this target?"
            models.Index(fields=["team", "target_type", "target_id"], name="entity_dep_target_idx"),
            # "What does this source reference?" and the per-source diff in sync_dependencies.
            models.Index(fields=["team", "source_type", "source_id"], name="entity_dep_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source_type}:{self.source_id} -> {self.target_type}:{self.target_id} ({self.role})"
