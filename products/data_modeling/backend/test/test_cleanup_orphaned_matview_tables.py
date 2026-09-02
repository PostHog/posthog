from posthog.test.base import BaseTest
from unittest.mock import patch

from products.data_modeling.backend.management.commands.cleanup_orphaned_matview_tables import (
    CLEANED,
    SKIPPED_DEPENDENTS,
    SKIPPED_MANAGED,
    SKIPPED_SHARED_TABLE,
    cascade_delete,
    find_half_deleted_matviews,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestFindHalfDeletedMatviews(BaseTest):
    def _table(self, name: str, deleted: bool = False) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(team=self.team, name=name, format="Parquet", deleted=deleted)

    def _saved_query(self, name: str, table: DataWarehouseTable | None, deleted: bool) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "select 1"}, table=table, deleted=deleted
        )

    def _node(self, sq: DataWarehouseSavedQuery, dag_name: str = "Default") -> Node:
        dag, _ = DAG.objects.get_or_create(team=self.team, name=dag_name)
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
        # Safety guard: a live query still points at the table — never cascade (would delete a live
        # table). The guard must also hold inside cascade_delete itself: a live query can acquire
        # the table between batch selection and the cascade reaching this row.
        table = self._table("shared_view")
        dead = self._saved_query("old_view", table, deleted=True)
        self._node(dead)
        self._saved_query("shared_view", table, deleted=False)
        assert self._found() == set()

        assert cascade_delete(dead) == SKIPPED_SHARED_TABLE
        table.refresh_from_db()
        dead.refresh_from_db()
        assert not table.deleted
        assert dead.table_id == table.id
        assert Node.objects.filter(saved_query=dead).exists()

    def test_partially_cleaned_row_stays_selected_until_soft_delete_completes(self):
        # The state a cascade crash leaves behind: node gone, table soft-deleted, but joins live
        # and the original name still occupied. The row must stay in the population so a re-run
        # resumes it — soft_delete's deleted_name is the terminal marker, not node/table presence.
        table = self._table("done_view", deleted=True)
        sq = self._saved_query("done_view", table, deleted=True)
        join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="done_view",
            source_table_key="id",
            joining_table_name="events",
            joining_table_key="id",
            field_name="done_view",
        )
        assert self._found() == {sq.id}

        assert cascade_delete(sq) == CLEANED
        sq.refresh_from_db()
        join.refresh_from_db()
        assert sq.deleted_name == "done_view"
        assert sq.name.startswith("POSTHOG_DELETED_")
        assert join.deleted
        assert self._found() == set()

    def test_live_query_is_untouched(self):
        table = self._table("healthy_view")
        sq = self._saved_query("healthy_view", table, deleted=False)
        self._node(sq)
        assert self._found() == set()

    def test_managed_viewset_query_is_excluded(self):
        # The managed viewset owns its views' lifecycle; delete_saved_query refuses these outright,
        # so the cascade must never revert one out-of-band and leave sync_views() to discover it.
        viewset = DataWarehouseManagedViewSet.objects.create(team=self.team, kind="revenue_analytics")
        table = self._table("managed_view")
        sq = self._saved_query("managed_view", table, deleted=True)
        sq.managed_viewset = viewset
        sq.save()
        self._node(sq)

        assert self._found() == set()
        assert cascade_delete(sq) == SKIPPED_MANAGED

    def test_dependent_in_another_dag_blocks_the_cascade(self):
        # delete_node_from_dag deletes EVERY node of the query but its HasDependentsError guard only
        # inspects one arbitrary node, so a dependent living in a different DAG can slip past it and
        # have its edge cascade-deleted and its source table reverted underneath it.
        dead = self._saved_query("shared_upstream", self._table("shared_upstream"), deleted=True)
        self._node(dead, dag_name="Default")  # created first, so .first() tends to pick it
        upstream_elsewhere = self._node(dead, dag_name="other_dag")

        live = self._saved_query("depends_on_it", None, deleted=False)
        dependent_node = self._node(live, dag_name="other_dag")
        Edge.objects.create(team=self.team, dag=dependent_node.dag, source=upstream_elsewhere, target=dependent_node)

        assert cascade_delete(dead) == SKIPPED_DEPENDENTS
        assert Node.objects.filter(saved_query=dead).count() == 2  # nothing deleted
        dead.refresh_from_db()
        assert dead.table_id is not None  # table not reverted

    def test_one_failure_does_not_abort_the_batch(self):
        from django.core.management import call_command

        for name in ("first_view", "second_view"):
            sq = self._saved_query(name, self._table(name), deleted=True)
            self._node(sq, dag_name=f"dag_{name}")

        module = "products.data_modeling.backend.management.commands.cleanup_orphaned_matview_tables"
        with patch(f"{module}.cascade_delete", side_effect=[RuntimeError("boom"), "cleaned"]) as cascade:
            call_command("cleanup_orphaned_matview_tables", "--team-id", str(self.team.pk), "--apply")

        assert cascade.call_count == 2  # the second query still got its turn

    def test_properly_deleted_query_with_ghost_node_is_excluded(self):
        # deleted_name is set => it went through the real soft_delete(); a lingering node here is a
        # separate, much larger population this cleanup must not touch.
        sq = self._saved_query("POSTHOG_DELETED_x", None, deleted=True)
        sq.deleted_name = "old_name"
        sq.save()
        self._node(sq)
        assert self._found() == set()
