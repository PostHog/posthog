from posthog.test.base import BaseTest

from products.data_modeling.backend.management.commands.cleanup_orphaned_matview_tables import (
    find_half_deleted_matviews,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestFindHalfDeletedMatviews(BaseTest):
    def _table(self, name: str, deleted: bool = False) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(team=self.team, name=name, format="Parquet", deleted=deleted)

    def _saved_query(self, name: str, table: DataWarehouseTable | None, deleted: bool) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "select 1"}, table=table, deleted=deleted
        )

    def _node(self, sq: DataWarehouseSavedQuery) -> Node:
        dag = DAG.objects.create(team=self.team, name="Default")
        return Node.objects.create(team=self.team, dag=dag, name=sq.name, type=NodeType.MAT_VIEW, saved_query=sq)

    def _found(self) -> set:
        return set(find_half_deleted_matviews().values_list("id", flat=True))

    def test_orphan_with_live_table_and_node_is_found(self):
        table = self._table("leaked_view")
        sq = self._saved_query("leaked_view", table, deleted=True)
        self._node(sq)
        assert self._found() == {sq.id}

    def test_node_only_orphan_is_found(self):
        # The post-table-cleanup state: table already soft-deleted, but the ghost node lingers.
        table = self._table("gone_view", deleted=True)
        sq = self._saved_query("gone_view", table, deleted=True)
        self._node(sq)
        assert self._found() == {sq.id}

    def test_table_shared_with_a_live_query_is_excluded(self):
        # Safety guard: a live query still points at the table — never cascade (would delete a live table).
        table = self._table("shared_view")
        dead = self._saved_query("old_view", table, deleted=True)
        self._node(dead)
        self._saved_query("shared_view", table, deleted=False)
        assert self._found() == set()

    def test_fully_deleted_query_is_skipped(self):
        # deleted, no node, table already soft-deleted — nothing left to clean.
        table = self._table("done_view", deleted=True)
        self._saved_query("done_view", table, deleted=True)
        assert self._found() == set()

    def test_live_query_is_untouched(self):
        table = self._table("healthy_view")
        sq = self._saved_query("healthy_view", table, deleted=False)
        self._node(sq)
        assert self._found() == set()

    def test_properly_deleted_query_with_ghost_node_is_excluded(self):
        # deleted_name is set => it went through the real soft_delete(); a lingering node here is a
        # separate, much larger population this cleanup must not touch.
        sq = self._saved_query("POSTHOG_DELETED_x", None, deleted=True)
        sq.deleted_name = "old_name"
        sq.save()
        self._node(sq)
        assert self._found() == set()
