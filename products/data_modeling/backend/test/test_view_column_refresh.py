import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.errors import QueryError
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.query import execute_hogql_query

from posthog.models import PropertyDefinition

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

    @parameterized.expand(
        [
            ("select_star", "SELECT * FROM downstream_view"),
            ("select_renamed_column", "SELECT new_id FROM downstream_view"),
            ("select_qualified_renamed_column", "SELECT v.new_id FROM downstream_view AS v"),
        ]
    )
    def test_query_over_views_whose_upstream_renamed_a_column_refreshes_their_columns(
        self, _name: str, sql: str
    ) -> None:
        upstream = self._create_view("upstream_view", "SELECT 1 AS old_id")
        middle = self._create_view("middle_view", "SELECT * FROM upstream_view")
        downstream = self._create_view("downstream_view", "SELECT * FROM middle_view")
        self._edit_view(upstream, "SELECT 1 AS new_id")

        response = execute_hogql_query(sql, team=self.team, user=self.user)

        assert response.columns == ["new_id"]
        assert response.results == [(1,)]
        for view in (middle, downstream):
            view.refresh_from_db()
            assert view.column_order == ["new_id"]

    def test_query_by_a_property_restricted_reader_leaves_stale_columns_untouched(self) -> None:
        upstream = self._create_view("upstream_view", "SELECT 1 AS old_id")
        downstream = self._create_view("downstream_view", "SELECT * FROM upstream_view")
        self._edit_view(upstream, "SELECT 1 AS new_id")

        with (
            patch(
                "products.data_modeling.backend.logic.view_column_refresh.get_restricted_properties_with_group_type_index_for_team",
                return_value={RestrictedProperty(name="$email", property_type=PropertyDefinition.Type.EVENT)},
            ),
            pytest.raises(QueryError),
        ):
            execute_hogql_query("SELECT new_id FROM downstream_view", team=self.team, user=self.user)

        downstream.refresh_from_db()
        assert downstream.column_order == ["old_id"]
