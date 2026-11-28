from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class NotebookModel(TeamScopedRootMixin):
    node = models.OneToOneField("data_modeling.Node", on_delete=models.CASCADE, primary_key=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    notebook_id = models.UUIDField()
    output_cell = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64)
    owner_id = models.BigIntegerField()
    table_id = models.UUIDField(null=True)
    latest_run_id = models.UUIDField(null=True)
    published_run_id = models.UUIDField(null=True)

    class Meta:
        db_table = "posthog_notebookmodel"
