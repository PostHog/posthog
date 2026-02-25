from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.data_modeling.backend.models import Node
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.services.saved_query_dag_sync import get_dag_id
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


class TestSavedQueryDagSyncIntegration(APIBaseTest):
    """Integration tests verifying SavedQuery API operations sync to DAG."""

    def test_create_saved_query_syncs_to_dag(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "dag_sync_create_test",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        saved_query = DataWarehouseSavedQuery.objects.get(id=response.json()["id"])
        node = Node.objects.filter(saved_query=saved_query).first()

        assert node is not None
        assert node.saved_query is not None
        self.assertEqual(node.saved_query.name, "dag_sync_create_test")
        self.assertEqual(node.type, NodeType.VIEW)
        self.assertEqual(node.dag_id_text, get_dag_id(self.team.id))

    def test_update_saved_query_syncs_to_dag(self):
        # create
        create_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "dag_sync_update_test",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        saved_query_id = create_response.json()["id"]
        latest_history_id = create_response.json().get("latest_history_id")

        # update
        update_response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/",
            {
                "name": "dag_sync_update_test_renamed",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 2",
                },
                "edited_history_id": latest_history_id,
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
        node = Node.objects.filter(saved_query=saved_query).first()
        assert node is not None
        assert node.saved_query is not None
        self.assertEqual(node.saved_query.name, "dag_sync_update_test_renamed")

    def test_delete_saved_query_removes_from_dag(self):
        # create
        create_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "dag_sync_delete_test",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        saved_query_id = create_response.json()["id"]
        self.assertTrue(Node.objects.filter(saved_query_id=saved_query_id).exists())

        # delete
        delete_response = self.client.delete(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/"
        )
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Node.objects.filter(saved_query_id=saved_query_id).exists())

    @patch("products.data_warehouse.backend.api.saved_query.sync_saved_query_workflow")
    @patch("products.data_warehouse.backend.api.saved_query.saved_query_workflow_exists", return_value=False)
    def test_materialize_updates_node_type(self, _mock_workflow_exists, _mock_sync_workflow):
        # create
        create_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "dag_sync_materialize_test",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        saved_query_id = create_response.json()["id"]
        node = Node.objects.get(saved_query_id=saved_query_id)
        self.assertEqual(node.type, NodeType.VIEW)

        # materialize
        materialize_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/materialize/"
        )
        self.assertEqual(materialize_response.status_code, status.HTTP_200_OK)
        node.refresh_from_db()
        self.assertEqual(node.type, NodeType.MAT_VIEW)

    @patch("products.data_warehouse.backend.api.saved_query.saved_query_workflow_exists", return_value=True)
    def test_revert_materialization_updates_node_type(self, _mock_workflow_exists):
        # create materialized
        create_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "dag_sync_revert_test",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        saved_query_id = create_response.json()["id"]

        # manually set node type to matview and is_materialized flag
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
        saved_query.is_materialized = True
        saved_query.save()

        node = Node.objects.get(saved_query=saved_query)
        node.type = NodeType.MAT_VIEW
        node.save()

        # revert materialization
        with patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule"):
            revert_response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/revert_materialization/"
            )
        self.assertEqual(revert_response.status_code, status.HTTP_200_OK)
        node.refresh_from_db()
        self.assertEqual(node.type, NodeType.VIEW)

    def test_dag_sync_failure_does_not_fail_saved_query_operation(self):
        """Verify that DAG sync failures don't break the main operation."""
        with patch(
            "products.data_modeling.backend.services.saved_query_dag_sync.sync_saved_query_to_dag",
            side_effect=Exception("DAG sync failed"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/",
                {
                    "name": "dag_sync_failure_test",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "SELECT 1",
                    },
                },
                format="json",
            )
        # should still exist on dag sync failure
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(DataWarehouseSavedQuery.objects.filter(id=response.json()["id"]).exists())
