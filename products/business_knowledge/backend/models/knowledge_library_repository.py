from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .knowledge_library import KnowledgeLibrary


class KnowledgeLibraryRepository(TeamScopedRootMixin, UUIDModel):
    """Membership of one selected GitHub repository in one library. The allowlist, not this row, decides what can be read."""

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    library = models.ForeignKey(KnowledgeLibrary, on_delete=models.CASCADE, related_name="repository_links")
    repo = models.CharField(max_length=255)

    class Meta:
        db_table = "posthog_business_knowledge_knowledgelibraryrepository"
        constraints = [
            models.UniqueConstraint(fields=["library", "repo"], name="bk_lib_repo_unique"),
        ]
        indexes = [
            models.Index(fields=["team", "repo"], name="bk_lib_repo_team_repo"),
        ]
