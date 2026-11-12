from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UpdatedMetaFields, UUIDModel, sane_repr

from products.data_modeling.backend.facade.contracts import MaterializationEngine


class NodeEngineTable(TeamScopedRootMixin, UpdatedMetaFields, UUIDModel):
    """The table one engine wrote for a DAG node.

    `DataWarehouseSavedQuery.table` stays the ClickHouse copy that every reader uses today. An
    engine that builds its own copy records it here, so the pointer for that engine moves without
    touching what a ClickHouse reader sees.
    """

    # No FK constraint on posthog_team: it would lock that hot table. TeamScopedRootMixin scopes the team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    node = models.ForeignKey("data_modeling.Node", on_delete=models.CASCADE, db_index=False, related_name="+")
    engine = models.CharField(max_length=20, choices=MaterializationEngine.choices)
    table = models.ForeignKey("warehouse_sources.DataWarehouseTable", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("node_id", "engine", "table_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["node", "engine"], name="unique_node_engine_table"),
        ]
        indexes = [
            models.Index(fields=["team", "engine"], name="dm_node_engine_table_team"),
        ]
