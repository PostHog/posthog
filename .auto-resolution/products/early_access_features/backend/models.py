from typing import TYPE_CHECKING

from django.db import models
from django.db.models import QuerySet

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import RootTeamMixin, UUIDTModel, sane_repr

if TYPE_CHECKING:
    from posthog.models.team import Team


class EarlyAccessFeature(FileSystemSyncMixin, RootTeamMixin, UUIDTModel):
    class Meta:
        db_table = "posthog_earlyaccessfeature"
        managed = True

    class Stage(models.TextChoices):
        DRAFT = "draft", "draft"
        CONCEPT = "concept", "concept"
        ALPHA = "alpha", "alpha"
        BETA = "beta", "beta"
        GENERAL_AVAILABILITY = "general-availability", "general availability"
        ARCHIVED = "archived", "archived"

    ReleaseStage = [Stage.CONCEPT, Stage.ALPHA, Stage.BETA, Stage.GENERAL_AVAILABILITY]

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="features",
        related_query_name="feature",
    )
    feature_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="features",
        related_query_name="feature",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    stage = models.CharField(max_length=40, choices=Stage.choices)
    documentation_url = models.URLField(max_length=800, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    __repr__ = sane_repr("id", "name", "team_id", "stage")

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["EarlyAccessFeature"]:
        base_qs = cls.objects.filter(team=team)
        return cls._filter_unfiled_queryset(base_qs, team, type="early_access_feature", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Early Access Features"),
            type="early_access_feature",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/early_access_features/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": None,
            },
            should_delete=False,
        )
