from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.data_warehouse.backend.models import DataWarehouseSavedQuery


class Node(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    # TODO(andrew): add something to alert the user that deleting a saved query that is used in a DAG
    # can really fuck things up. deleting the saved query deletes the node which deletes all edges
    # where the node is either the source or the target (big blast radius for something small)
    saved_query = models.OneToOneField(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingnode"
