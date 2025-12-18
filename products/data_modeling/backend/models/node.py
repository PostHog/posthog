from django.db import models
from django.db.models import Q

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.data_warehouse.backend.models import DataWarehouseSavedQuery


class NodeType(models.TextChoices):
    TABLE = "table"
    VIEW = "view"
    MAT_VIEW = "matview"


class Node(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    # models.PROTECT prevents deleting a saved query if its referenced by a Node
    saved_query = models.OneToOneField(DataWarehouseSavedQuery, on_delete=models.PROTECT, null=True, blank=True)
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True)
    # fully qualified name for sources, name of the view/mat view for refs
    name = models.TextField(max_length=2048)
    # type of the node (source table, view, or mat view)
    type = models.TextField(max_length=16, choices=NodeType.choices, default=NodeType.TABLE)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingnode"
        constraints = [
            models.CheckConstraint(
                name="saved_query_required_on_non_table_node_type",
                check=Q(type=NodeType.TABLE) | Q(saved_query__isnull=False),
            ),
            models.UniqueConstraint(
                name="name_unique_within_team_dag",
                fields=["team", "dag_id", "name"],
            ),
        ]
