import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError

from products.data_modeling.backend.models.node import Node, NodeType
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


@pytest.mark.django_db
class TestNodeNameSync(BaseTest):
    def test_node_name_syncs_from_saved_query_on_save(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="original_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node = Node.objects.create(
            team=self.team,
            dag_id_text="test",
            name="ignored_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        self.assertEqual(node.name, "original_name")

    def test_node_name_cannot_be_overridden_when_saved_query_exists(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="saved_query_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node = Node.objects.create(
            team=self.team,
            dag_id_text="test",
            name="saved_query_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        node.name = "attempted_override"
        node.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "saved_query_name")

    def test_node_name_updates_when_saved_query_name_changes(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="original_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node = Node.objects.create(
            team=self.team,
            dag_id_text="test",
            name="original_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        saved_query.name = "updated_name"
        saved_query.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "updated_name")

    def test_table_node_name_is_not_affected_by_sync(self):
        node = Node.objects.create(
            team=self.team,
            dag_id_text="test",
            name="events",
            saved_query=None,
            type=NodeType.TABLE,
        )

        self.assertEqual(node.name, "events")

        node.name = "custom_table_name"
        node.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "custom_table_name")

    def test_node_without_saved_query_requires_name(self):
        with self.assertRaises(ValueError) as context:
            Node.objects.create(
                team=self.team,
                dag_id_text="test",
                name="",
                saved_query=None,
                type=NodeType.TABLE,
            )

        self.assertEqual(str(context.exception), "Node without a saved_query must have a name")

    def test_multiple_nodes_can_share_saved_query_across_different_dags(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="shared_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        node1 = Node.objects.create(
            team=self.team,
            dag_id_text="dag_one",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )
        node2 = Node.objects.create(
            team=self.team,
            dag_id_text="dag_two",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        self.assertEqual(node1.saved_query_id, node2.saved_query_id)
        self.assertEqual(node1.name, "shared_view")
        self.assertEqual(node2.name, "shared_view")

        saved_query.name = "renamed_view"
        saved_query.save()

        node1.refresh_from_db()
        node2.refresh_from_db()
        self.assertEqual(node1.name, "renamed_view")
        self.assertEqual(node2.name, "renamed_view")

    def test_multiple_nodes_cannot_share_saved_query_in_same_dag(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="shared_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        Node.objects.create(
            team=self.team,
            dag_id_text="dag_one",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )
        with pytest.raises(IntegrityError):
            Node.objects.create(
                team=self.team,
                dag_id_text="dag_one",
                saved_query=saved_query,
                type=NodeType.VIEW,
            )
