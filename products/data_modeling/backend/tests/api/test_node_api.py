from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.models import DAG, Edge, Node, NodeType
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestNodeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = f"posthog_{self.team.id}"
        self.dag = DAG.objects.create(team=self.team, name=self.dag_id)

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        self.table_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="events",
            type=NodeType.TABLE,
        )

        self.view_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        Edge.objects.create(
            team=self.team,
            dag=self.dag,
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
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        Node.objects.create(
            team=other_team,
            dag=other_dag,
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
        self.assertEqual(response.json()["dag"], str(self.dag.id))

    def test_get_node_includes_upstream_downstream_counts(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["upstream_count"], 0)
        self.assertEqual(response.json()["downstream_count"], 0)

    def test_list_nodes_with_dag_filter(self):
        another_dag = DAG.objects.create(team=self.team, name="another_dag")
        Node.objects.create(
            team=self.team,
            dag=another_dag,
            name="another_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/?dag={another_dag.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "another_table")

    def test_list_nodes_without_dag_filter_returns_all(self):
        another_dag = DAG.objects.create(team=self.team, name="another_dag")
        Node.objects.create(
            team=self.team,
            dag=another_dag,
            name="another_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 3)

    @parameterized.expand(
        [
            # node target wins even when the saved-query interval disagrees (tiered v2 teams
            # carry NULL intervals, so a saved-query-only read shows a blank frequency)
            ("target_first", timedelta(hours=6), timedelta(hours=12), "6hour"),
            ("saved_query_fallback", None, timedelta(hours=12), "12hour"),
            ("neither", None, None, None),
        ]
    )
    def test_node_sync_interval_reads_target_first(
        self,
        _name: str,
        target: timedelta | None,
        saved_query_interval: timedelta | None,
        expected: str | None,
    ):
        self.saved_query.sync_frequency_interval = saved_query_interval
        self.saved_query.save(update_fields=["sync_frequency_interval"])
        if target is not None:
            set_declared_target(self.view_node, target)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["sync_interval"], expected)

    def test_node_response_includes_dag_name(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["dag_name"], self.dag_id)

    def test_dag_ids_action(self):
        another_dag = DAG.objects.create(team=self.team, name="another_dag")
        Node.objects.create(
            team=self.team,
            dag=another_dag,
            name="another_table",
            type=NodeType.TABLE,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/dag_ids/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dag_names = {d["name"] for d in response.json()["dag_ids"]}
        self.assertEqual(dag_names, {"another_dag", self.dag_id})

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

    @patch("products.data_modeling.backend.presentation.views.node.sync_connect")
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

    @patch("products.data_modeling.backend.presentation.views.node.sync_connect")
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

    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialize_starts_workflow(self, mock_sync_connect):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_client.start_workflow.assert_called_once()

    @patch("products.data_modeling.backend.presentation.views.node.feature_enabled_or_false", return_value=True)
    @patch("products.data_modeling.backend.presentation.views.node.sync_connect")
    def test_run_uses_execute_dag_when_v2_enabled(self, mock_sync_connect, mock_feature_flag):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-execute-dag")

    @patch("products.data_modeling.backend.presentation.views.node.feature_enabled_or_false", return_value=False)
    @patch("products.data_modeling.backend.presentation.views.node.sync_connect")
    def test_run_uses_run_workflow_when_v2_disabled(self, mock_sync_connect, mock_feature_flag):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/run/",
            {"direction": "upstream"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-run")

    @patch("products.data_modeling.backend.presentation.views.node.feature_enabled_or_false", return_value=True)
    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialize_uses_materialize_view_when_v2_enabled(self, mock_sync_connect, mock_feature_flag):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-materialize-view")

    @patch("products.data_modeling.backend.presentation.views.node.feature_enabled_or_false", return_value=False)
    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    def test_materialize_uses_run_workflow_when_v2_disabled(self, mock_sync_connect, mock_feature_flag):
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/materialize/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_args = mock_client.start_workflow.call_args
        self.assertEqual(call_args[0][0], "data-modeling-run")

    def test_lineage_returns_subgraph(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.view_node.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(self.table_node.id), node_ids)
        edge_source_ids = {e["source_id"] for e in response.json()["edges"]}
        self.assertIn(str(self.table_node.id), edge_source_ids)

    def test_lineage_by_saved_query_id(self):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?saved_query_id={self.view_node.saved_query_id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(self.table_node.id), node_ids)

    def test_lineage_requires_node_id_or_saved_query_id(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(["node_id", "saved_query_id"])
    def test_lineage_invalid_uuid_returns_400(self, lookup_param):
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?{lookup_param}=not-a-uuid"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(["node_id", "saved_query_id"])
    def test_lineage_does_not_leak_other_teams_nodes(self, lookup_param):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_saved_query = DataWarehouseSavedQuery.objects.create(
            name="other_view", team=other_team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        other_node = Node.objects.create(
            team=other_team, dag=other_dag, saved_query=other_saved_query, type=NodeType.VIEW
        )

        lookup_value = other_node.id if lookup_param == "node_id" else other_saved_query.id
        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?{lookup_param}={lookup_value}"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_lineage_multi_level(self):
        sq_b = DataWarehouseSavedQuery.objects.create(
            name="view_b", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        sq_c = DataWarehouseSavedQuery.objects.create(
            name="view_c", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        view_b = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="view_b",
            type=NodeType.VIEW,
            saved_query=sq_b,
        )
        view_c = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="view_c",
            type=NodeType.VIEW,
            saved_query=sq_c,
        )
        Edge.objects.create(team=self.team, dag=self.dag, source=self.view_node, target=view_b)
        Edge.objects.create(team=self.team, dag=self.dag, source=view_b, target=view_c)

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={view_b.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertIn(str(self.table_node.id), node_ids)
        self.assertIn(str(self.view_node.id), node_ids)
        self.assertIn(str(view_b.id), node_ids)
        self.assertIn(str(view_c.id), node_ids)

    def test_lineage_no_dependencies(self):
        sq_standalone = DataWarehouseSavedQuery.objects.create(
            name="standalone", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        standalone = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="standalone",
            type=NodeType.VIEW,
            saved_query=sq_standalone,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={standalone.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["nodes"]), 1)
        self.assertEqual(response.json()["nodes"][0]["id"], str(standalone.id))
        self.assertEqual(len(response.json()["edges"]), 0)

    def test_lineage_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_table = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_table",
            type=NodeType.TABLE,
        )
        other_sq = DataWarehouseSavedQuery.objects.create(
            name="other_view", team=other_team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        other_view = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_view",
            type=NodeType.VIEW,
            saved_query=other_sq,
        )
        Edge.objects.create(
            team=other_team,
            dag=other_dag,
            source=other_table,
            target=other_view,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/data_modeling_nodes/lineage/?node_id={self.view_node.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        node_ids = {n["id"] for n in response.json()["nodes"]}
        self.assertNotIn(str(other_table.id), node_ids)
        self.assertNotIn(str(other_view.id), node_ids)

    @parameterized.expand(["post", "put", "patch"])
    def test_dag_field_rejects_other_teams_dag(self, method):
        other_team = Team.objects.create(organization=self.organization)
        foreign_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")

        if method == "post":
            response = self.client.post(
                f"/api/environments/{self.team.id}/data_modeling_nodes/",
                data={"name": "new_table", "type": NodeType.TABLE, "dag": str(foreign_dag.id)},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(Node.objects.filter(name="new_table", dag=foreign_dag).exists())
            return

        original_dag_id = self.view_node.dag_id
        url = f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/"
        if method == "patch":
            response = self.client.patch(url, data={"dag": str(foreign_dag.id)}, format="json")
        else:
            response = self.client.put(
                url,
                data={"name": "test_view", "type": NodeType.VIEW, "dag": str(foreign_dag.id)},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.view_node.refresh_from_db()
        self.assertEqual(self.view_node.dag_id, original_dag_id)

    @parameterized.expand(["put", "patch"])
    def test_saved_query_id_cannot_be_bound_to_other_teams_query(self, method):
        other_team = Team.objects.create(organization=self.organization)
        foreign_sq = DataWarehouseSavedQuery.objects.create(
            name="leaked_name",
            team=other_team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )

        original_saved_query_id = self.view_node.saved_query_id
        url = f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/"
        if method == "patch":
            self.client.patch(url, data={"saved_query_id": str(foreign_sq.id)}, format="json")
        else:
            self.client.put(
                url,
                data={
                    "name": "test_view",
                    "type": NodeType.VIEW,
                    "dag": str(self.dag.id),
                    "saved_query_id": str(foreign_sq.id),
                },
                format="json",
            )

        self.view_node.refresh_from_db()
        self.assertEqual(self.view_node.saved_query_id, original_saved_query_id)
        self.assertNotEqual(self.view_node.name, foreign_sq.name)

    def _create_managed_node(self) -> Node:
        managed_dag = DAG.get_or_create_revenue_analytics(self.team)
        sq = DataWarehouseSavedQuery.objects.create(
            name="managed_view", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        return Node.objects.create(
            team=self.team, dag=managed_dag, saved_query=sq, type=NodeType.VIEW, description="orig"
        )

    def test_cannot_delete_node_in_managed_dag(self):
        node = self._create_managed_node()

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_nodes/{node.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Node.objects.filter(id=node.id).exists())

    def test_cannot_patch_node_in_managed_dag(self):
        node = self._create_managed_node()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{node.id}/",
            data={"description": "changed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        node.refresh_from_db()
        self.assertEqual(node.description, "orig")

    @parameterized.expand(["post", "patch"])
    def test_cannot_add_or_move_node_into_managed_dag(self, method):
        managed_dag = DAG.get_or_create_revenue_analytics(self.team)

        if method == "post":
            response = self.client.post(
                f"/api/environments/{self.team.id}/data_modeling_nodes/",
                data={"name": "sneaky", "type": NodeType.TABLE, "dag": str(managed_dag.id)},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(Node.objects.filter(name="sneaky", dag=managed_dag).exists())
            return

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_nodes/{self.view_node.id}/",
            data={"dag": str(managed_dag.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.view_node.refresh_from_db()
        self.assertEqual(self.view_node.dag_id, self.dag.id)


class TestEdgeViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dag_id = f"posthog_{self.team.id}"
        self.dag = DAG.objects.create(team=self.team, name=self.dag_id)

        self.source_node = Node.objects.create(
            team=self.team,
            dag=self.dag,
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
            dag=self.dag,
            saved_query=self.saved_query,
            type=NodeType.VIEW,
        )

        self.edge = Edge.objects.create(
            team=self.team,
            dag=self.dag,
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
        self.assertEqual(edge["dag"], str(self.dag.id))

    def test_list_edges_with_dag_filter(self):
        another_dag = DAG.objects.create(team=self.team, name="another_dag")
        another_source = Node.objects.create(
            team=self.team,
            dag=another_dag,
            name="another_events",
            type=NodeType.TABLE,
        )
        another_target = Node.objects.create(
            team=self.team,
            dag=another_dag,
            name="another_view",
            type=NodeType.TABLE,
        )
        Edge.objects.create(
            team=self.team,
            dag=another_dag,
            source=another_source,
            target=another_target,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/?dag={another_dag.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["source_id"], str(another_source.id))

    def test_edge_response_includes_dag_name(self):
        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"][0]["dag_name"], self.dag_id)

    def test_list_edges_filters_by_team(self):
        other_team = Team.objects.create(organization=self.organization)
        other_dag = DAG.objects.create(team=other_team, name=f"posthog_{other_team.id}")
        other_source = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_events",
            type=NodeType.TABLE,
        )
        other_target = Node.objects.create(
            team=other_team,
            dag=other_dag,
            name="other_view",
            type=NodeType.TABLE,
        )
        Edge.objects.create(
            team=other_team,
            dag=other_dag,
            source=other_source,
            target=other_target,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/data_modeling_edges/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def _create_managed_edge(self) -> Edge:
        managed_dag = DAG.get_or_create_revenue_analytics(self.team)
        source = Node.objects.create(team=self.team, dag=managed_dag, name="m_events", type=NodeType.TABLE)
        sq = DataWarehouseSavedQuery.objects.create(
            name="m_view", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        target = Node.objects.create(team=self.team, dag=managed_dag, saved_query=sq, type=NodeType.VIEW)
        return Edge.objects.create(team=self.team, dag=managed_dag, source=source, target=target, properties={"a": 1})

    def test_cannot_delete_edge_in_managed_dag(self):
        edge = self._create_managed_edge()

        response = self.client.delete(f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Edge.objects.filter(id=edge.id).exists())

    def test_cannot_patch_edge_in_managed_dag(self):
        edge = self._create_managed_edge()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/data_modeling_edges/{edge.id}/",
            data={"properties": {"a": 2}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        edge.refresh_from_db()
        self.assertEqual(edge.properties, {"a": 1})
