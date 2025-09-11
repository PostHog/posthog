from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDTModel


class QueryTabState(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    state = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="""
            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey
            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.
            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables
            for a user.
            """,
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "created_by"], name="unique_team_created_by")]
