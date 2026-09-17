from datetime import timedelta

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from products.data_modeling.backend.logic.node_frequency import (
    get_declared_target,
    saved_query_target_bounds,
    set_declared_target,
)
from products.data_modeling.backend.management.commands.repair_trapped_matviews import (
    DEFAULT_TARGET,
    clamp_to_bounds,
    target_for,
    trapped_saved_queries,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

COMMAND = "products.data_modeling.backend.management.commands.repair_trapped_matviews"


class TestTrappedSavedQueries(BaseTest):
    def _saved_query(
        self,
        name: str,
        *,
        is_materialized: bool = True,
        table: DataWarehouseTable | None = None,
        origin: str = DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE,
        sync_frequency_interval: timedelta | None = None,
    ) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "select 1"},
            is_materialized=is_materialized,
            table=table,
            origin=origin,
            sync_frequency_interval=sync_frequency_interval,
        )

    def _node(self, sq: DataWarehouseSavedQuery, node_type: str = NodeType.VIEW) -> Node:
        dag, _ = DAG.objects.get_or_create(team=self.team, name="Default")
        return Node.objects.create(team=self.team, dag=dag, name=sq.name, type=node_type, saved_query=sq)

    def _found(self) -> set:
        return {sq.id for sq in trapped_saved_queries(team_id=None)}

    def test_a_materialized_query_with_no_table_typed_view_is_trapped(self):
        sq = self._saved_query("lost_its_table")
        self._node(sq)
        assert self._found() == {sq.id}

    def test_a_managed_viewset_is_left_alone(self):
        # The materialize action refuses these outright, so the flag is a provisioning artifact.
        sq = self._saved_query("revenue_view", origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET)
        self._node(sq)
        assert self._found() == set()

    def test_an_endpoint_query_is_left_alone(self):
        sq = self._saved_query("an_endpoint", origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
        self._node(sq)
        assert self._found() == set()

    def test_a_query_that_still_has_its_table_is_left_alone(self):
        table = DataWarehouseTable.objects.create(team=self.team, name="healthy", format="Parquet")
        sq = self._saved_query("healthy", table=table)
        self._node(sq, node_type=NodeType.MAT_VIEW)
        assert self._found() == set()

    def test_a_deliberately_unmaterialized_view_is_left_alone(self):
        sq = self._saved_query("just_a_view", is_materialized=False)
        self._node(sq)
        assert self._found() == set()


class TestTargetForTrappedQuery(BaseTest):
    """The node type alone does not make a model run — without a target it joins no cadence tier."""

    def _trapped(self, name: str, sync_frequency_interval: timedelta | None = None) -> DataWarehouseSavedQuery:
        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "select 1"},
            is_materialized=True,
            sync_frequency_interval=sync_frequency_interval,
        )
        dag, _ = DAG.objects.get_or_create(team=self.team, name="Default")
        Node.objects.create(team=self.team, dag=dag, name=name, type=NodeType.VIEW, saved_query=sq)
        return sq

    def test_a_target_the_node_already_declares_wins(self):
        sq = self._trapped("declares_both", sync_frequency_interval=timedelta(days=1))
        node = Node.objects.get(saved_query=sq)
        set_declared_target(node, timedelta(hours=1))
        assert target_for(sq) == timedelta(hours=1)

    def test_the_leftover_v1_interval_is_used_when_the_node_declares_nothing(self):
        sq = self._trapped("declares_interval", sync_frequency_interval=timedelta(minutes=30))
        assert get_declared_target(Node.objects.get(saved_query=sq)) is None
        assert target_for(sq) == timedelta(minutes=30)

    def test_a_query_declaring_nothing_falls_back_to_the_default(self):
        sq = self._trapped("declares_nothing")
        assert target_for(sq) == DEFAULT_TARGET


class TestClampingTheTargetToWhatTheDagAccepts(BaseTest):
    """`target_for` guesses, and the write refuses a guess slower than a consumer downstream."""

    def _trapped(self, name: str) -> Node:
        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "select 1"},
            is_materialized=True,
        )
        dag, _ = DAG.objects.get_or_create(team=self.team, name="Default")
        return Node.objects.create(team=self.team, dag=dag, name=name, type=NodeType.VIEW, saved_query=sq)

    def _consumer_of(self, node: Node, target: timedelta) -> None:
        name = f"{node.name}_consumer"
        consumer_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": f"select * from {node.name}"},
            is_materialized=True,
        )
        consumer = Node.objects.create(
            team=self.team, dag=node.dag, name=name, type=NodeType.MAT_VIEW, saved_query=consumer_query
        )
        set_declared_target(consumer, target)
        Edge.objects.create(team=self.team, dag=node.dag, source=node, target=consumer)

    def test_a_guess_slower_than_a_consumer_is_pulled_up_to_it(self):
        node = self._trapped("feeds_an_hourly_view")
        self._consumer_of(node, timedelta(hours=1))
        assert clamp_to_bounds(node.saved_query, timedelta(days=1)) == timedelta(hours=1)

    def test_a_guess_the_dag_already_accepts_is_left_alone(self):
        node = self._trapped("fast_enough")
        self._consumer_of(node, timedelta(hours=1))
        assert clamp_to_bounds(node.saved_query, timedelta(minutes=15)) == timedelta(minutes=15)

    def test_a_v1_interval_that_is_not_a_bucket_lands_on_one(self):
        # v1 never constrained `sync_frequency_interval` to a schedulable bucket, so a trapped
        # query can prefer a cadence no tier runs at. The write refuses that as readily as one
        # outside the bounds, so the clamp has to return a member, not just something in range.
        node = self._trapped("prefers_ninety_minutes")
        self._consumer_of(node, timedelta(hours=6))
        target = clamp_to_bounds(node.saved_query, timedelta(minutes=90))
        bounds = saved_query_target_bounds(self.team.pk, node.saved_query_id)
        assert bounds is not None
        assert target in bounds.bounds.allowed

    def test_a_query_no_node_carries_keeps_its_preference(self):
        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="nodeless",
            query={"kind": "HogQLQuery", "query": "select 1"},
            is_materialized=True,
        )
        assert clamp_to_bounds(sq, DEFAULT_TARGET) == DEFAULT_TARGET


class TestRepairReconcilesTheDag(BaseTest):
    """Retyping a trapped node changes what the DAG's existing schedule runs, so the repair must
    reconcile the DAG or a legacy whole-DAG schedule wakes up and then blocks tiering."""

    def _trapped(self, name: str) -> DataWarehouseSavedQuery:
        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "select 1"},
            is_materialized=True,
            origin=DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE,
        )
        dag, _ = DAG.objects.get_or_create(team=self.team, name="Default")
        Node.objects.create(team=self.team, dag=dag, name=name, type=NodeType.VIEW, saved_query=sq)
        return sq

    def test_apply_reconciles_each_touched_dag_once_after_retyping(self):
        self._trapped("a")
        self._trapped("b")
        with mock.patch(f"{COMMAND}.reconcile_dag_schedules", return_value=True) as reconcile:
            call_command("repair_trapped_matviews", "--apply", "--team-id", self.team.id)
        assert Node.objects.filter(team=self.team, type=NodeType.MAT_VIEW).count() == 2
        reconcile.assert_called_once()
        assert reconcile.call_args.args[0] == DAG.objects.get(team=self.team, name="Default")

    def test_dry_run_never_reconciles(self):
        self._trapped("a")
        with mock.patch(f"{COMMAND}.reconcile_dag_schedules") as reconcile:
            call_command("repair_trapped_matviews", "--team-id", self.team.id)
        reconcile.assert_not_called()
        assert Node.objects.filter(team=self.team, type=NodeType.VIEW).count() == 1
