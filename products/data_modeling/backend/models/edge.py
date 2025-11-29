from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Edge(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    source = models.ForeignKey("data_modeling.Node", related_name="outgoing_edges", on_delete=models.CASCADE)
    target = models.ForeignKey("data_modeling.Node", related_name="incoming_edges", on_delete=models.CASCADE)
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingedge"
        constraints = [
            models.UniqueConstraint(fields=["dag_id", "source", "target"], name="unique_within_dag"),
        ]
