from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Edge(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source = models.ForeignKey(
        "data_modeling.Node", related_name="source", on_delete=models.CASCADE, null=True, blank=True
    )
    target = models.ForeignKey(
        "data_modeling.Node", related_name="target", on_delete=models.CASCADE, null=True, blank=True
    )
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingedge"
