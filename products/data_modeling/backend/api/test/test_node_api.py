from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models import Team

from products.data_modeling.backend.models import Edge, Node, NodeType
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


class TestNodeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = "test_dag"

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        self.table_node = Node.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            name="events",
            type=NodeType.TABLE,
        )

        self.view_node = Node.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        Edge.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            source=self.table_node,
            target=self.view_node,
        )

    def test_list_nodes(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

        names = {node["name"] for node in response.json()["results"]}
        self.assertEqual(names, {"events", "test_view"})

    def test_list_nodes_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        Node.objects.create(
            team=other_team,
            dag_id=self.dag_id,
            name="other_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

    def test_get_node(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "test_view")
        self.assertEqual(response.json()["type"], "view")
        self.assertEqual(response.json()["dag_id"], self.dag_id)

    def test_get_node_includes_upstream_downstream_counts(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["upstream_count"], 0)
        self.assertEqual(response.json()["downstream_count"], 0)

    def test_dag_ids_action(self):
        Node.objects.create(
            team=self.team,
            dag_id="another_dag",
            name="another_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/dag_ids/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.json()["dag_ids"]), {"another_dag", self.dag_id})

    def test_run_requires_direction(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("direction", response.json()["error"])

    def test_run_rejects_invalid_direction(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "invalid"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_run_rejects_table_nodes(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.table_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("table", response.json()["error"].lower())

    @patch("products.data_modeling.backend.api.node.sync_connect")
    def test_run_upstream_starts_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(self.view_node.id), response.json()["node_ids"])
        mock_client.start_workflow.assert_called_once()

    @patch("products.data_modeling.backend.api.node.sync_connect")
    def test_run_downstream_starts_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "downstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_client.start_workflow.assert_called_once()

    def test_materialize_rejects_table_nodes(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.table_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("table", response.json()["error"].lower())

    @patch("products.data_modeling.backend.api.node.sync_connect")
    def test_materialize_starts_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_client.start_workflow.assert_called_once()


class TestEdgeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = "test_dag"

        self.source_node = Node.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            name="events",
            type=NodeType.TABLE,
        )

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        self.target_node = Node.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        self.edge = Edge.objects.create(
            team=self.team,
            dag_id=self.dag_id,
            source=self.source_node,
            target=self.target_node,
        )

    def test_list_edges(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        edge = response.json()["results"][0]
        self.assertEqual(edge["source_id"], str(self.source_node.id))
        self.assertEqual(edge["target_id"], str(self.target_node.id))
        self.assertEqual(edge["dag_id"], self.dag_id)

    def test_list_edges_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_source = Node.objects.create(
            team=other_team,
            dag_id=self.dag_id,
            name="other_events",
            type=NodeType.TABLE,
        )
        other_target = Node.objects.create(
            team=other_team,
            dag_id=self.dag_id,
            name="other_view",
            type=NodeType.TABLE,
        )
        Edge.objects.create(
            team=other_team,
            dag_id=self.dag_id,
            source=other_source,
            target=other_target,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
