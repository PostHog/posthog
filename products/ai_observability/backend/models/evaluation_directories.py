from django.db import models
from django.db.models.functions import Lower

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class EvaluationDirectory(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    name = models.CharField(max_length=400)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )

    class Meta:
        db_table = "llm_analytics_evaluationdirectory"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "team",
                name="uniq_llma_eval_dir_team_name_ci",
            )
        ]

    def __str__(self) -> str:
        return self.name
