from django.db import models
from django.db.models.functions import Lower

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class KnowledgeLibrary(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """A retrieval scope. Sources and repositories belong to it through link rows, so deleting it drops those links only."""

    activity_logging_on_delete = True

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    name = models.CharField(max_length=255)
    # Set only when learning files a new source. A person can rename the row. Deleting it unlinks members.
    is_default = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_business_knowledge_knowledgelibrary"
        constraints = [
            models.UniqueConstraint("team", Lower("name"), name="bk_library_team_name_ci"),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_default=True),
                name="bk_library_one_default",
            ),
        ]

    def __str__(self) -> str:
        return self.name
