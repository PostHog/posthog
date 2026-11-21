from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.data_modeling.backend.facade.contracts import MaterializationEngine
from products.data_modeling.backend.facade.models import NodeEngineTable
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.test.helpers import saved_query_node
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestNodeEngineTable(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dag = DAG.get_or_create_default(self.team)
        self.node = saved_query_node(self.team, self.dag, "orders", NodeType.VIEW)

    def _table(self, name: str) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(team=self.team, name=name, format="Parquet")

    def _record(self, table: DataWarehouseTable) -> NodeEngineTable:
        return NodeEngineTable.objects.for_team(self.team.id).create(
            team_id=self.team.id, node=self.node, engine=MaterializationEngine.TRINO, table=table
        )

    def test_a_node_has_one_table_per_engine(self) -> None:
        self._record(self._table("orders_run_1"))

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._record(self._table("orders_run_2"))

        assert NodeEngineTable.objects.for_team(self.team.id).filter(node=self.node).count() == 1

    def test_deleting_a_node_drops_its_pointer_and_keeps_the_table(self) -> None:
        table = self._table("orders_run_1")
        self._record(table)

        self.node.delete()

        assert not NodeEngineTable.objects.for_team(self.team.id).exists()
        assert DataWarehouseTable.objects.filter(pk=table.pk).exists()
