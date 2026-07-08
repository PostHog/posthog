from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.data_modeling.backend.logic.freshness import (
    STREAMING,
    UnsatisfiableFrequencyError,
    compute_effective_cadences,
    declared_target_bounds,
    validate_declared_target,
)
from products.data_modeling.backend.logic.node_frequency import (
    build_frequency_graph,
    get_declared_target,
    resolve_source_intervals,
    seed_targets,
    set_declared_target,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)
DAY = timedelta(days=1)


def _table_node(team: Team, dag: DAG, name: str, properties: dict) -> Node:
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def _saved_query_node(team: Team, dag: DAG, name: str, node_type: str) -> Node:
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


def _warehouse_source_node(
    team: Team,
    dag: DAG,
    *,
    sync_frequency_interval: timedelta | None,
    should_sync: bool = True,
    with_schema: bool = True,
) -> Node:
    table = DataWarehouseTable.objects.create(name="stripe_charges", team=team)
    if with_schema:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="posthog_test_",
        )
        ExternalDataSchema.objects.create(
            name="stripe_charges",
            team=team,
            source=source,
            table=table,
            sync_frequency_interval=sync_frequency_interval,
            should_sync=should_sync,
        )
    return _table_node(team, dag, "stripe_charges", {"origin": "warehouse", "warehouse_table_id": str(table.id)})


@pytest.mark.django_db
class TestFrequencyTargetAccessors(BaseTest):
    def _node(self) -> Node:
        return _table_node(self.team, DAG.get_or_create_default(self.team), "events", {"origin": "posthog"})

    def test_round_trip(self):
        node = self._node()
        set_declared_target(node, M15)
        node.refresh_from_db()
        self.assertEqual(get_declared_target(node), M15)

    def test_none_clears_the_target(self):
        node = self._node()
        set_declared_target(node, M15)
        set_declared_target(node, None)
        node.refresh_from_db()
        self.assertIsNone(get_declared_target(node))

    def test_setting_target_preserves_sibling_system_state(self):
        node = self._node()
        node.properties = {"system": {"suspended": {"duckdb": True}}}
        node.save(update_fields=["properties"])
        set_declared_target(node, H1)
        node.refresh_from_db()
        self.assertEqual(node.properties["system"]["suspended"], {"duckdb": True})
        self.assertEqual(get_declared_target(node), H1)


@pytest.mark.django_db
class TestResolveSourceIntervals(BaseTest):
    @property
    def _dag(self) -> DAG:
        return DAG.get_or_create_default(self.team)

    def test_posthog_builtin_is_streaming_unflagged(self):
        node = _table_node(self.team, self._dag, "events", {"origin": "posthog"})
        intervals, best_effort = resolve_source_intervals([node])
        self.assertEqual(intervals, {str(node.id): STREAMING})
        self.assertEqual(best_effort, set())

    def test_unknown_origin_is_streaming_but_flagged(self):
        node = _table_node(self.team, self._dag, "mystery", {})
        intervals, best_effort = resolve_source_intervals([node])
        self.assertEqual(intervals, {str(node.id): STREAMING})
        self.assertEqual(best_effort, {str(node.id)})

    def test_scheduled_import_uses_its_interval(self):
        node = _warehouse_source_node(self.team, self._dag, sync_frequency_interval=H6)
        intervals, best_effort = resolve_source_intervals([node])
        self.assertEqual(intervals, {str(node.id): H6})
        self.assertEqual(best_effort, set())

    @parameterized.expand(
        [
            ("manual_never_synced", None, True),
            ("paused_schema", H6, False),
        ]
    )
    def test_unscheduled_import_is_streaming_but_flagged(self, _name, interval, should_sync):
        node = _warehouse_source_node(self.team, self._dag, sync_frequency_interval=interval, should_sync=should_sync)
        intervals, best_effort = resolve_source_intervals([node])
        self.assertEqual(intervals, {str(node.id): STREAMING})
        self.assertEqual(best_effort, {str(node.id)})


@pytest.mark.django_db
class TestBuildFrequencyGraph(BaseTest):
    def test_endpoint_target_propagates_to_matview_over_streamed_source(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        graph = build_frequency_graph(dag)
        effective = compute_effective_cadences(
            nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets
        )

        self.assertEqual(effective[str(matview.id)], M15)
        floor, _ceiling = declared_target_bounds(
            node_id=str(matview.id),
            edges=graph.edges,
            declared_targets=graph.declared_targets,
            source_intervals=graph.source_intervals,
        )
        self.assertEqual(floor, STREAMING)

    def test_imported_source_floor_makes_a_tighter_descendant_unsatisfiable(self):
        dag = DAG.get_or_create_default(self.team)
        source = _warehouse_source_node(self.team, dag, sync_frequency_interval=H6)
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)

        graph = build_frequency_graph(dag)
        floor, _ceiling = declared_target_bounds(
            node_id=str(matview.id),
            edges=graph.edges,
            declared_targets=graph.declared_targets,
            source_intervals=graph.source_intervals,
        )
        self.assertEqual(floor, H6)
        with self.assertRaises(UnsatisfiableFrequencyError):
            validate_declared_target(
                node_id=str(matview.id),
                target=M15,
                edges=graph.edges,
                declared_targets=graph.declared_targets,
                source_intervals=graph.source_intervals,
            )


@pytest.mark.django_db
class TestSeedTargets(BaseTest):
    def _view_node_in_dag_with(self, *, saved_query_interval, dag_interval) -> tuple[DAG, Node]:
        dag = DAG.objects.create(team=self.team, name="seed-demo", sync_frequency_interval=dag_interval)
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="v",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=saved_query_interval,
        )
        node = Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.VIEW)
        return dag, node

    @parameterized.expand(
        [
            ("saved_query_interval_wins", H1, DAY, H1),
            ("falls_back_to_dag_interval", None, DAY, DAY),
            ("no_signal_leaves_node_unseeded", None, None, None),
        ]
    )
    def test_seed(self, _name, saved_query_interval, dag_interval, expected):
        dag, node = self._view_node_in_dag_with(saved_query_interval=saved_query_interval, dag_interval=dag_interval)
        seeds = seed_targets(dag)
        self.assertEqual(seeds, {} if expected is None else {str(node.id): expected})

    def test_source_tables_are_never_seeded(self):
        dag = DAG.objects.create(team=self.team, name="seed-demo-src", sync_frequency_interval=H1)
        _table_node(self.team, dag, "events", {"origin": "posthog"})
        self.assertEqual(seed_targets(dag), {})
