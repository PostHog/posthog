from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class DataWarehouseSavedQueryFolder(CreatedMetaFields, UUIDTModel, UpdatedMetaFields):
    name = models.CharField(
        max_length=128,
        help_text="Display name for the folder used to organize saved queries in the SQL editor sidebar.",
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="posthog_datawarehouse_saved_query_folder_unique_name",
            )
        ]
        db_table = "posthog_datawarehousesavedqueryfolder"
