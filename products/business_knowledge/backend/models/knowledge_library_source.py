from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .knowledge_library import KnowledgeLibrary
from .knowledge_source import KnowledgeSource


class KnowledgeLibrarySource(TeamScopedRootMixin, UUIDModel):
    """Membership of one source in one library. Deleting either side deletes this row and leaves the other in place."""

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    library = models.ForeignKey(KnowledgeLibrary, on_delete=models.CASCADE, related_name="source_links")
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="library_links")

    class Meta:
        db_table = "posthog_business_knowledge_knowledgelibrarysource"
        constraints = [
            models.UniqueConstraint(fields=["library", "source"], name="bk_lib_source_unique"),
        ]
        indexes = [
            models.Index(fields=["team", "source"], name="bk_lib_source_team_source"),
        ]
