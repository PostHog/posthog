from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class GitHubSyncedModel(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    saved_query = models.OneToOneField(
        "data_warehouse.DataWarehouseSavedQuery",
        on_delete=models.CASCADE,
        related_name="github_synced_model",
    )

    file_path = models.TextField(help_text="Path relative to repo root, e.g. 'models/revenue.sql'")
    file_sha = models.CharField(max_length=64, help_text="Git blob SHA for change detection")
    last_synced_sha = models.CharField(max_length=64, help_text="Commit SHA when this model was last synced")

    class Meta:
        app_label = "data_modeling"
        db_table = "posthog_datamodelinggithubsyncedmodel"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "file_path"],
                name="unique_team_file_path",
            ),
        ]
