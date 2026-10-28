from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestViewColumnRefresh(ClickhouseTestMixin, BaseTest):
    def _create_view(self, name: str, sql: str) -> DataWarehouseSavedQuery:
        view = DataWarehouseSavedQuery(team=self.team, name=name, query={"kind": "HogQLQuery", "query": sql})
        view.set_columns(view.get_columns(user=self.user))
        view.save()
        sync_saved_query_to_dag(view, reconcile=False)
        return view

    def _edit_view(self, view: DataWarehouseSavedQuery, sql: str) -> None:
        view.query = {"kind": "HogQLQuery", "query": sql}
        view.set_columns(view.get_columns(user=self.user))
        view.save()

    def test_select_star_over_views_whose_upstream_renamed_a_column_refreshes_their_columns(self) -> None:
        upstream = self._create_view("upstream_view", "SELECT 1 AS old_id")
        middle = self._create_view("middle_view", "SELECT * FROM upstream_view")
        downstream = self._create_view("downstream_view", "SELECT * FROM middle_view")
        self._edit_view(upstream, "SELECT 1 AS new_id")

        response = execute_hogql_query("SELECT * FROM downstream_view", team=self.team, user=self.user)

        assert response.columns == ["new_id"]
        assert response.results == [(1,)]
        for view in (middle, downstream):
            view.refresh_from_db()
            assert view.column_order == ["new_id"]
