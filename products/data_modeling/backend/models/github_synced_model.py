from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class GitHubSyncedModel(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    team_id: int

    config = models.ForeignKey(
        "data_modeling.GitHubSyncConfig",
        on_delete=models.CASCADE,
        related_name="synced_models",
    )
    config_id: int

    saved_query = models.OneToOneField(
        "data_warehouse.DataWarehouseSavedQuery",
        on_delete=models.CASCADE,
        related_name="github_synced_model",
    )
    saved_query_id: int

    file_path = models.TextField(help_text="Path relative to repo root, e.g. 'models/revenue.sql'")
    file_sha = models.CharField(max_length=64, help_text="Git blob SHA for change detection")
    last_synced_sha = models.CharField(max_length=64, help_text="Commit SHA when this model was last synced")

    def __str__(self) -> str:
        return f"GitHubSyncedModel {self.file_path}"

    class Meta:
        app_label = "data_modeling"
        db_table = "posthog_datamodelinggithubsyncedmodel"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "file_path"],
                name="unique_team_file_path",
            ),
        ]
