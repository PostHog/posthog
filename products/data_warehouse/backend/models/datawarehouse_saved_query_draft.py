from django.db import models

from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel


class DataWarehouseSavedQueryDraft(CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    """
    Draft version of a saved query that allows users to iterate on queries
    before materializing them as actual saved queries.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    query = models.JSONField(default=dict, blank=True, help_text="HogQL query draft")

    # 255 should be safe. the max length of a view name is 128
    name = models.CharField(max_length=255, null=True, blank=True, help_text="Name of the draft")

    saved_query = models.ForeignKey(
        "data_warehouse.DataWarehouseSavedQuery",
        # if a team member deletes the saved query, check if null and provide option to create view again
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Original saved query this draft is editing (optional)",
    )

    edited_history_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="view history id that the draft branched from"
    )

    class Meta:
        db_table = "posthog_datawarehousesavedquerydraft"
