from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .constants import LearningProvider, LearningRunResult, LearningRunStatus, learning_provider_choices

LEARNING_ERROR_MAX_LENGTH = 1024
LEARNING_PROVIDER_MAX_LENGTH = 64
LEARNING_ANALYSIS_VERSION_MAX_LENGTH = 128
LEARNING_EVIDENCE_KEY_MAX_LENGTH = 255


class KnowledgeLearningRun(TeamScopedRootMixin, UUIDModel):
    """One analysis of one evidence revision for a canonical team.

    Rejected and no-knowledge outcomes still get a row so the coordinator does not
    re-analyze the same resolution every tick.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        # Unique and (team, status, analysis_version) already lead with team_id.
        db_index=False,
        related_name="+",
    )
    provider = models.CharField(
        max_length=LEARNING_PROVIDER_MAX_LENGTH,
        choices=learning_provider_choices,
        default=LearningProvider.CONVERSATIONS,
    )
    # Latest public human comment identifies the resolved-thread revision.
    # Same ticket + same comment is idempotent; a later human reply is a new run.
    evidence_key = models.CharField(max_length=LEARNING_EVIDENCE_KEY_MAX_LENGTH)
    # Environment the ticket lives in. `team` is the canonical parent.
    source_team_id = models.PositiveIntegerField()
    analysis_version = models.CharField(max_length=LEARNING_ANALYSIS_VERSION_MAX_LENGTH)
    status = models.CharField(
        max_length=16,
        choices=LearningRunStatus.choices,
        default=LearningRunStatus.PENDING,
    )
    result = models.CharField(
        max_length=32,
        choices=LearningRunResult.choices,
        blank=True,
        default="",
    )
    # Plain UUID so deleting a generated document does not cascade into this row,
    # and coordinator sweeps never take locks on KnowledgeDocument.
    knowledge_document_id = models.UUIDField(null=True, blank=True)
    error = models.CharField(max_length=LEARNING_ERROR_MAX_LENGTH, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "provider", "evidence_key", "analysis_version"],
                name="bk_learn_run_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status", "analysis_version"], name="bk_learn_run_team_status"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.evidence_key} ({self.status})"
