from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class Edge(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, editable=False)
    # the source node of the edge (i.e. the node this edge is pointed away from)
    source = models.ForeignKey(
        "data_modeling.Node", related_name="outgoing_edges", on_delete=models.CASCADE, editable=False
    )
    # the target node of the edge (i.e. the node this edge is pointed toward)
    target = models.ForeignKey(
        "data_modeling.Node", related_name="incoming_edges", on_delete=models.CASCADE, editable=False
    )
    # the name of the DAG this edge belongs to
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True, editable=False)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingedge"
        constraints = [
            models.UniqueConstraint(fields=["dag_id", "source", "target"], name="unique_within_dag"),
        ]
