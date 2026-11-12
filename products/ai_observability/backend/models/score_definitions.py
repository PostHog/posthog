from __future__ import annotations

from typing import Any

from django.db import models, transaction

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.tagged_items_relation import Taggable
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class StaleScoreDefinitionVersion(Exception):
    """Raised when a caller's `base_version` no longer matches the scorer's current version."""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"Scorer current version is {current_version}.")
        self.current_version = current_version


class ScoreDefinition(Taggable, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Calculation(models.TextChoices):
        REPORTED = "reported", "Reported"
        COMPOSITE = "composite", "Composite"

    class Kind(models.TextChoices):
        CATEGORICAL = "categorical", "categorical"
        NUMERIC = "numeric", "numeric"
        BOOLEAN = "boolean", "boolean"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=40, blank=True, default="", db_default="")
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=32, choices=Kind)
    calculation = models.CharField(
        max_length=16, choices=Calculation, default=Calculation.REPORTED, db_default="reported"
    )
    archived = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    current_version = models.ForeignKey(
        "ScoreDefinitionVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "llm_analytics_scoredefinition"
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["team", "kind", "archived"], name="llma_score_def_team_kind_idx")]

    @transaction.atomic
    def create_new_version(
        self,
        *,
        config: dict[str, Any],
        created_by: User | None,
        base_version: int | None = None,
        composition: dict[str, Any] | None = None,
    ) -> ScoreDefinitionVersion:
        definition = (
            ScoreDefinition.objects.select_for_update(of=("self",)).select_related("current_version").get(pk=self.pk)
        )
        current_version_number = definition.current_version.version if definition.current_version is not None else 0

        # Optimistic concurrency check inside the row lock — two writers seeing the same `base_version`
        # before the lock would otherwise both pass; one must lose here once the lock serializes them.
        if base_version is not None and base_version != current_version_number:
            raise StaleScoreDefinitionVersion(current_version=current_version_number)

        version = ScoreDefinitionVersion.objects.create(
            definition=definition,
            version=current_version_number + 1,
            config=config,
            composition=composition,
            created_by=created_by,
        )
        if composition is not None:
            ScoreDefinitionInput.objects.for_team(definition.team_id, canonical=True).bulk_create(
                [
                    ScoreDefinitionInput(
                        team_id=definition.team_id,
                        composite_version=version,
                        input_version_id=dependency["scorer_version_id"],
                        alias=dependency["alias"],
                    )
                    for dependency in composition["inputs"]
                ]
            )

        definition.current_version = version
        definition.updated_by = created_by
        definition.save(update_fields=["current_version", "updated_at", "updated_by"])

        self.current_version = version
        self.updated_by = created_by
        return version


class ScoreDefinitionVersion(UUIDModel, CreatedMetaFields):
    definition = models.ForeignKey(ScoreDefinition, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    config = models.JSONField(default=dict)
    composition = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "llm_analytics_scoredefinitionversion"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version"],
                name="uniq_llma_score_def_ver",
            )
        ]
        indexes = [
            models.Index(fields=["definition", "-version"], name="llma_score_def_ver_def_idx"),
            models.Index(fields=["created_at"], name="llma_score_def_ver_created_idx"),
        ]


class ScoreDefinitionInput(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    composite_version = models.ForeignKey(ScoreDefinitionVersion, on_delete=models.CASCADE, related_name="inputs")
    input_version = models.ForeignKey(ScoreDefinitionVersion, on_delete=models.RESTRICT, related_name="dependents")
    alias = models.CharField(max_length=32)

    class Meta:
        db_table = "llm_analytics_scoredefinitioninput"
        constraints = [
            models.UniqueConstraint(fields=["composite_version", "alias"], name="aio_composite_input_alias_uniq"),
        ]
