from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel, UpdatedMetaFields


class DataWarehouseSavedQueryDraft(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    """
    Draft version of a saved query that allows users to iterate on queries
    before materializing them as actual saved queries.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    query = models.JSONField(default=dict, null=True, blank=True, help_text="HogQL query draft")

    saved_query = models.ForeignKey(
        "posthog.DataWarehouseSavedQuery",
        # if a team member deletes the saved query, check if null and provide option to create view again
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Original saved query this draft is editing (optional)",
    )
