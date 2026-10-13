from io import StringIO

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType

GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"


class TestReenableMaterialization(BaseTest):
    def _saved_query(self, name: str, *, with_node: bool = True, deleted: bool = False) -> DataWarehouseSavedQuery:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            is_materialized=False,
            deleted=deleted,
        )
        if with_node:
            Node.objects.create(team=self.team, dag=self.dag, saved_query=saved_query, type=NodeType.MAT_VIEW)
        return saved_query

    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="Default")

    def test_dry_run_changes_nothing(self):
        switched_off = self._saved_query("switched_off")
        call_command("reenable_materialization", saved_query_ids=str(switched_off.id), stdout=StringIO())
        switched_off.refresh_from_db()
        assert switched_off.is_materialized is False

    def test_apply_reenables_only_live_queries_that_can_be_scheduled(self):
        switched_off = self._saved_query("switched_off")
        deleted = self._saved_query("deleted", deleted=True)
        nodeless = self._saved_query("nodeless", with_node=False)
        out = StringIO()
        with mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}):
            call_command(
                "reenable_materialization",
                saved_query_ids=",".join(str(sq.id) for sq in (switched_off, deleted, nodeless)),
                apply=True,
                stdout=out,
            )

        for saved_query in (switched_off, deleted, nodeless):
            saved_query.refresh_from_db()
        assert switched_off.is_materialized is True
        assert deleted.is_materialized is False
        assert nodeless.is_materialized is False
        assert "Re-enabled 1, failed 1." in out.getvalue()
