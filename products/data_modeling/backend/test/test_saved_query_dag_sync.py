import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from products.data_modeling.backend.models import Edge, Node
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.services.saved_query_dag_sync import (
    HasDependentsError,
    delete_node_from_dag,
    get_conflict_dag_id,
    get_dag_id,
    get_dependent_saved_queries,
    sync_saved_query_to_dag,
    update_node_type,
)
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


@pytest.mark.django_db
class TestGetDagId(BaseTest):
    def test_get_dag_id_returns_expected_format(self):
        self.assertEqual(get_dag_id(123), "posthog_123")
        self.assertEqual(get_dag_id(1), "posthog_1")

    def test_get_conflict_dag_id_has_correct_prefix(self):
        conflict_id = get_conflict_dag_id(123)
        self.assertTrue(conflict_id.startswith("conflict_"))
        self.assertTrue(conflict_id.endswith("_posthog_123"))


@pytest.mark.django_db
class TestSyncSavedQueryToDag(BaseTest):
    def test_sync_creates_dag_model(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        sync_saved_query_to_dag(saved_query)

        dag = DAG.objects.get(team=self.team, name=get_dag_id(self.team.id))
        self.assertEqual(dag.name, f"posthog_{self.team.id}")

    def test_sync_reuses_existing_dag_model(self):
        existing_dag = DAG.objects.create(team=self.team, name=get_dag_id(self.team.id))

        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(saved_query)

        self.assertEqual(DAG.objects.filter(team=self.team, name=get_dag_id(self.team.id)).count(), 1)
        self.assertEqual(DAG.objects.get(team=self.team, name=get_dag_id(self.team.id)).id, existing_dag.id)

    def test_sync_creates_node_for_saved_query(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node = sync_saved_query_to_dag(saved_query)
        # use explicit assert for mypy's dumb ass
        assert node is not None
        self.assertEqual(node.name, "test_view")
        self.assertEqual(node.team, self.team)
        self.assertEqual(node.dag_id_text, get_dag_id(self.team.id))
        self.assertEqual(node.type, NodeType.VIEW)
        self.assertEqual(node.saved_query, saved_query)

    def test_sync_creates_table_node_for_posthog_source(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )

        node = sync_saved_query_to_dag(saved_query)

        events_node = Node.objects.filter(
            team=self.team,
            dag_id_text=get_dag_id(self.team.id),
            name="events",
        ).first()

        assert events_node is not None
        self.assertEqual(events_node.type, NodeType.TABLE)
        self.assertEqual(events_node.properties.get("origin"), "posthog")

        # edge from events -> test_view
        edge = Edge.objects.filter(source=events_node, target=node).first()
        self.assertIsNotNone(edge)

    def test_sync_creates_edges_for_multiple_dependencies(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={
                "query": "SELECT e.*, p.* FROM events e JOIN persons p ON e.person_id = p.id",
                "kind": "HogQLQuery",
            },
        )

        node = sync_saved_query_to_dag(saved_query)

        # events -> test_view and persons -> test_view
        incoming_edges = Edge.objects.filter(target=node)
        source_names = {edge.source.name for edge in incoming_edges}
        self.assertIn("events", source_names)
        self.assertIn("persons", source_names)

    def test_sync_updates_existing_node(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        before = sync_saved_query_to_dag(saved_query)

        saved_query.name = "updated_view"
        saved_query.save()
        after = sync_saved_query_to_dag(saved_query)

        assert before is not None
        assert after is not None

        self.assertEqual(before.id, after.id)
        after.refresh_from_db()
        self.assertEqual(after.name, "updated_view")

    def test_sync_deletes_old_edges_when_dependencies_change(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )

        node = sync_saved_query_to_dag(saved_query)

        # initially depends on events
        edge = Edge.objects.filter(target=node).first()
        assert edge is not None
        self.assertEqual(Edge.objects.filter(target=node).count(), 1)
        self.assertEqual(edge.source.name, "events")

        # change to depend on persons instead
        saved_query.query = {"query": "SELECT * FROM persons", "kind": "HogQLQuery"}
        saved_query.save()
        sync_saved_query_to_dag(saved_query)

        edge = Edge.objects.filter(target=node).first()
        assert edge is not None
        self.assertEqual(Edge.objects.filter(target=node).count(), 1)
        self.assertEqual(edge.source.name, "persons")  # not events

    def test_sync_creates_edge_to_other_saved_query(self):
        upstream_query = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        upstream_node = sync_saved_query_to_dag(upstream_query)

        downstream_query = DataWarehouseSavedQuery.objects.create(
            name="downstream_view",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
        )
        downstream_node = sync_saved_query_to_dag(downstream_query)

        edge = Edge.objects.filter(source=upstream_node, target=downstream_node).first()
        self.assertIsNotNone(edge)

    def test_sync_creates_conflict_edge_on_cycle(self):
        query_a = DataWarehouseSavedQuery.objects.create(
            name="view_a",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        # no deps
        node_a = sync_saved_query_to_dag(query_a)

        query_b = DataWarehouseSavedQuery.objects.create(
            name="view_b",
            team=self.team,
            query={"query": "SELECT * FROM view_a", "kind": "HogQLQuery"},
        )
        # depends on a
        sync_saved_query_to_dag(query_b)

        # update a to depend on b (cycle)
        query_a.query = {"query": "SELECT * FROM view_b", "kind": "HogQLQuery"}
        query_a.save()
        sync_saved_query_to_dag(query_a)

        conflict_edges = Edge.objects.filter(dag_id_text__startswith="conflict_", target=node_a)
        self.assertEqual(conflict_edges.count(), 1)

        conflict_edge = conflict_edges.first()
        assert conflict_edge is not None
        self.assertEqual(conflict_edge.properties.get("error_type"), "cycle")
        self.assertIn("original_dag_id", conflict_edge.properties)
        self.assertEqual(conflict_edge.properties["original_dag_id"], get_dag_id(self.team.id))

    def test_sync_raises_for_empty_or_null_query(self):
        empty_query, _ = DataWarehouseSavedQuery.objects.get_or_create(
            name="test_view_empty_query",
            team=self.team,
            query={"query": "", "kind": "HogQLQuery"},
        )

        with self.assertRaises(ValueError):
            sync_saved_query_to_dag(empty_query)

        null_query, _ = DataWarehouseSavedQuery.objects.get_or_create(
            name="test_view_null_query",
            team=self.team,
            query={"query": None, "kind": "HogQLQuery"},
        )

        with self.assertRaises(ValueError):
            sync_saved_query_to_dag(null_query)

    @parameterized.expand(
        [
            ("select * from nonexistent_table",),
            ("select nonexistent_alias.* from events",),
            ("select * from events, persons",),  # ambiguous
        ]
    )
    def test_sync_raises_for_query_errors(self, query):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": query, "kind": "HogQLQuery"},
        )

        with pytest.raises(QueryError):
            sync_saved_query_to_dag(saved_query)


@pytest.mark.django_db
class TestDeleteNodeFromDag(BaseTest):
    def test_delete_removes_node(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(saved_query)

        self.assertEqual(Node.objects.filter(saved_query=saved_query).count(), 1)

        delete_node_from_dag(saved_query)

        self.assertEqual(Node.objects.filter(saved_query=saved_query).count(), 0)

        # doesn't update saved query name via soft delete
        saved_query.refresh_from_db()
        self.assertEqual(saved_query.name, "test_view")

    def test_delete_cascades_to_edges(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)

        self.assertTrue(Edge.objects.filter(target=node).exists())

        delete_node_from_dag(saved_query)

        self.assertFalse(Edge.objects.filter(target=node).exists())

    def test_delete_handles_nonexistent_node(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        # shouldn't raise
        delete_node_from_dag(saved_query)

    def test_delete_raises_error_when_has_dependents(self):
        upstream = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(upstream)
        downstream = DataWarehouseSavedQuery.objects.create(
            name="downstream_view",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(downstream)
        with self.assertRaises(HasDependentsError):
            delete_node_from_dag(upstream)

    def test_delete_succeeds_when_no_dependents(self):
        upstream = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(upstream)
        delete_node_from_dag(upstream)
        self.assertEqual(Node.objects.filter(saved_query=upstream).count(), 0)


@pytest.mark.django_db
class TestGetDependents(BaseTest):
    def test_get_dependents_returns_empty_when_no_dependents(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(saved_query)
        dependents = get_dependent_saved_queries(saved_query)
        self.assertEqual(dependents, [])

    def test_get_dependents_returns_immediate_dependents(self):
        upstream = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(upstream)
        downstream1 = DataWarehouseSavedQuery.objects.create(
            name="downstream1",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(downstream1)
        downstream2 = DataWarehouseSavedQuery.objects.create(
            name="downstream2",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(downstream2)
        dependents = get_dependent_saved_queries(upstream)
        dependent_names = {d.name for d in dependents}
        self.assertEqual(len(dependents), 2)
        self.assertIn("downstream1", dependent_names)
        self.assertIn("downstream2", dependent_names)

    def test_get_dependents_excludes_deleted_views(self):
        upstream = DataWarehouseSavedQuery.objects.create(
            name="upstream_view",
            team=self.team,
            query={"query": "SELECT * FROM events", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(upstream)
        downstream = DataWarehouseSavedQuery.objects.create(
            name="downstream_view",
            team=self.team,
            query={"query": "SELECT * FROM upstream_view", "kind": "HogQLQuery"},
        )
        sync_saved_query_to_dag(downstream)
        # soft delete the downstream view
        downstream.deleted = True
        downstream.save()
        dependents = get_dependent_saved_queries(upstream)
        self.assertEqual(dependents, [])

    def test_get_dependents_returns_empty_when_no_node(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        # no node exists
        dependents = get_dependent_saved_queries(saved_query)
        self.assertEqual(dependents, [])


@pytest.mark.django_db
class TestUpdateNodeType(BaseTest):
    def test_update_node_type(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        self.assertEqual(node.type, NodeType.VIEW)
        update_node_type(saved_query, NodeType.MAT_VIEW)
        node.refresh_from_db()
        self.assertEqual(node.type, NodeType.MAT_VIEW)
        update_node_type(saved_query, NodeType.VIEW)
        node.refresh_from_db()
        self.assertEqual(node.type, NodeType.VIEW)

    def test_update_handles_nonexistent_node(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        # shouldn't raise, exception is captured though
        update_node_type(saved_query, NodeType.MAT_VIEW)
        update_node_type(saved_query, NodeType.VIEW)


@pytest.mark.django_db
class TestSkipValidation(BaseTest):
    def test_skip_validation_bypasses_cycle_detection(self):
        query_a = DataWarehouseSavedQuery.objects.create(
            name="view_a",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node_a = Node.objects.create(
            team=self.team,
            dag_id_text=get_dag_id(self.team.id),
            name="view_a",
            saved_query=query_a,
            type=NodeType.VIEW,
        )
        query_b = DataWarehouseSavedQuery.objects.create(
            name="view_b",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node_b = Node.objects.create(
            team=self.team,
            dag_id_text=get_dag_id(self.team.id),
            name="view_b",
            saved_query=query_b,
            type=NodeType.VIEW,
        )
        # a -> b
        Edge.objects.create(
            team=self.team,
            dag_id_text=get_dag_id(self.team.id),
            source=node_a,
            target=node_b,
        )

        # shouldn't raise
        conflict_edge = Edge(
            team=self.team,
            dag_id_text=get_conflict_dag_id(self.team.id),
            source=node_b,
            target=node_a,
            properties={"error_type": "cycle"},
        )
        conflict_edge.save(skip_validation=True)

        self.assertTrue(Edge.objects.filter(id=conflict_edge.id).exists())

    def test_skip_validation_bypasses_dag_mismatch_check(self):
        query = DataWarehouseSavedQuery.objects.create(
            name="view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node_a = Node.objects.create(
            team=self.team,
            dag_id_text="dag_1",
            name="node_a",
            saved_query=query,
            type=NodeType.VIEW,
        )

        query_b = DataWarehouseSavedQuery.objects.create(
            name="view_b",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node_b = Node.objects.create(
            team=self.team,
            dag_id_text="dag_2",
            name="node_b",
            saved_query=query_b,
            type=NodeType.VIEW,
        )

        # shouldn't raise
        conflict_edge = Edge(
            team=self.team,
            dag_id_text=get_conflict_dag_id(self.team.id),
            source=node_a,
            target=node_b,
        )
        conflict_edge.save(skip_validation=True)
        self.assertTrue(Edge.objects.filter(id=conflict_edge.id).exists())
