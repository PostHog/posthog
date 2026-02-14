from django.db import models
from django.db.models import Q

from posthog.models import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.data_warehouse.backend.models import DataWarehouseSavedQuery


class NodeType(models.TextChoices):
    TABLE = "table"
    VIEW = "view"
    MAT_VIEW = "matview"


class Node(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    # models.PROTECT prevents deleting a saved query if its referenced by a Node
    saved_query = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.PROTECT, null=True, blank=True)
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True)
    # duplicate of dag_id, will replace it after code refs are migrated
    dag_id_text = models.TextField(max_length=256, default="posthog")
    # name of the source table, view, matview, etc.
    # for nodes with a saved_query, this is automatically synced from saved_query.name
    name = models.TextField(max_length=2048, db_index=True)
    # type of the node (source table, view, or mat view)
    type = models.TextField(max_length=16, choices=NodeType.choices, default=NodeType.TABLE)
    properties = models.JSONField(default=dict)

    def save(self, *args, **kwargs):
        # always inherit name from saved_query when one exists
        if self.saved_query is not None:
            self.name = self.saved_query.name
        elif not self.name:
            raise ValueError("Node without a saved_query must have a name")
        self.dag_id_text = self.dag_id
        super().save(*args, **kwargs)

    class Meta:
        db_table = "posthog_datamodelingnode"
        constraints = [
            models.CheckConstraint(
                name="saved_query_required_on_non_table_node_type",
                check=Q(type=NodeType.TABLE) | Q(saved_query__isnull=False),
            ),
            models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=False),
                name="saved_query_unique_within_team_dag",
                fields=["team", "dag_id_text", "saved_query"],
            ),
            models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=True),
                name="name_unique_within_team_dag_for_tables",
                fields=["team", "dag_id_text", "name"],
            ),
        ]
