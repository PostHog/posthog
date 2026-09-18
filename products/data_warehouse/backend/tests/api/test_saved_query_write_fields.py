import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.data_modeling.backend.facade.api import get_declared_target, set_declared_target
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Edge, Node


class TestSavedQueryWriteFields(APIBaseTest):
    def _create_view(self, **fields: Any) -> Any:
        return self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {"kind": "HogQLQuery", "query": "select event from events LIMIT 100"},
                **fields,
            },
        )

    def test_create_tolerates_an_edited_history_id(self) -> None:
        response = self._create_view(edited_history_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_frequency_failure_rolls_back_the_view(self) -> None:
        with patch("products.data_modeling.backend.facade.api.sync_saved_query_to_dag", side_effect=RuntimeError):
            response = self._create_view(sync_frequency="6hour")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(DataWarehouseSavedQuery.objects.filter(team=self.team, name="event_view").exists())

    @parameterized.expand([("supplied", True, 400), ("omitted", False, 201)])
    def test_create_reports_a_discarded_dag_placement_only_when_asked_for(
        self, _name: str, supply_dag_id: bool, expected_status: int
    ) -> None:
        dag = DAG.objects.create(team=self.team, name="Other")
        fields = {"dag_id": str(dag.id)} if supply_dag_id else {}
        with patch("products.data_modeling.backend.facade.api.sync_saved_query_to_dag", side_effect=RuntimeError):
            response = self._create_view(**fields)
        self.assertEqual(response.status_code, expected_status, response.content)
        self.assertEqual(
            DataWarehouseSavedQuery.objects.filter(team=self.team, name="event_view").exists(),
            expected_status == 201,
        )
        self.assertFalse(Node.objects.filter(dag=dag).exists())

    def test_create_applies_the_requested_dag_and_cadence(self) -> None:
        dag = DAG.objects.create(team=self.team, name="Other")
        response = self._create_view(dag_id=str(dag.id), sync_frequency="6hour")
        self.assertEqual(response.status_code, 201, response.content)
        node = Node.objects.get(saved_query_id=response.json()["id"])
        self.assertEqual(node.dag_id, dag.id)
        self.assertEqual(get_declared_target(node), timedelta(hours=6))

    @parameterized.expand([("create",), ("update",)])
    def test_managed_dag_is_rejected(self, operation: str) -> None:
        dag = DAG.get_or_create_revenue_analytics(self.team)
        if operation == "create":
            response = self._create_view(dag_id=str(dag.id))
        else:
            created = self._create_view().json()
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
                {"dag_id": str(dag.id)},
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(Node.objects.filter(dag=dag).exists())

    def test_deleted_cannot_be_set_through_the_write_api(self) -> None:
        created = self._create_view().json()
        url = f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}"
        response = self.client.patch(url, {"deleted": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(DataWarehouseSavedQuery.objects.get(id=created["id"]).deleted)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_create_rejects_an_unknown_dag_id(self) -> None:
        response = self._create_view(dag_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(DataWarehouseSavedQuery.objects.filter(team=self.team, name="event_view").exists())

    def test_create_does_not_upsert_a_deleted_view(self) -> None:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="event_view",
            query={"kind": "HogQLQuery", "query": "select event from events LIMIT 7"},
            deleted=True,
        )
        response = self._create_view(edited_history_id=str(view.query_revision))
        self.assertEqual(response.status_code, 400, response.content)
        view.refresh_from_db()
        self.assertEqual(view.query, {"kind": "HogQLQuery", "query": "select event from events LIMIT 7"})

    def test_dag_id_alone_reparents_the_node(self) -> None:
        created = self._create_view().json()
        node = Node.objects.get(saved_query_id=created["id"])
        set_declared_target(node, timedelta(hours=6))
        other = DAG.objects.create(team=self.team, name="Other")
        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
            {"dag_id": str(other.id)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        moved_node = Node.objects.get(saved_query_id=created["id"])
        self.assertEqual(moved_node.dag_id, other.id)
        self.assertEqual(moved_node.id, node.id)
        self.assertEqual(get_declared_target(moved_node), timedelta(hours=6))

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
            {
                "query": {"kind": "HogQLQuery", "query": "select event from events LIMIT 7"},
                "edited_history_id": created["latest_history_id"],
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Node.objects.get(saved_query_id=created["id"]).dag_id, other.id)

    def test_failed_move_preserves_the_node_and_its_parents(self) -> None:
        created = self._create_view().json()
        node = Node.objects.get(saved_query_id=created["id"])
        parents = set(Edge.objects.filter(target=node).values_list("id", flat=True))
        self.assertTrue(parents)
        other = DAG.objects.create(team=self.team, name="Other")
        with patch("products.data_modeling.backend.facade.api.sync_saved_query_to_dag", side_effect=RuntimeError):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
                {"dag_id": str(other.id)},
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Node.objects.get(id=node.id).dag_id, node.dag_id)
        self.assertEqual(set(Edge.objects.filter(target=node).values_list("id", flat=True)), parents)

    def test_update_rejects_another_teams_dag_id(self) -> None:
        created = self._create_view().json()
        foreign_team = self.create_team_with_organization(organization=self.organization)
        foreign_dag = DAG.objects.create(team=foreign_team, name="Foreign")
        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
            {
                "dag_id": str(foreign_dag.id),
                "query": {"kind": "HogQLQuery", "query": "select event from events LIMIT 7"},
                "edited_history_id": created["latest_history_id"],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Node.objects.filter(dag=foreign_dag).count(), 0)

    def test_reparenting_refuses_to_strand_dependents(self) -> None:
        created = self._create_view().json()
        consumer = self._create_view(
            name="consumer_view",
            query={"kind": "HogQLQuery", "query": "select event from event_view"},
        )
        self.assertEqual(consumer.status_code, 201, consumer.content)
        node = Node.objects.get(saved_query_id=created["id"])
        other = DAG.objects.create(team=self.team, name="Other")
        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
            {"dag_id": str(other.id)},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Node.objects.get(id=node.id).dag_id, node.dag_id)
        self.assertTrue(Edge.objects.filter(source=node, target__saved_query_id=consumer.json()["id"]).exists())
