from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .knowledge_library import KnowledgeLibrary


class KnowledgeKeyLibrary(TeamScopedRootMixin, UUIDModel):
    """Limits one project secret API key to one library. A key with no row reads the whole project."""

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        related_name="+",
    )
    key = models.OneToOneField(
        "posthog.ProjectSecretAPIKey",
        on_delete=models.CASCADE,
        # A database constraint would block a key delete that does not go through the ORM.
        db_constraint=False,
        related_name="+",
    )
    # Null after the library is deleted. The row stays, so the key reads nothing instead of the whole project.
    library = models.ForeignKey(KnowledgeLibrary, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_business_knowledge_knowledgekeylibrary"
