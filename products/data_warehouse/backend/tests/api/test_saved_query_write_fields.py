import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.data_modeling.backend.facade.api import get_declared_target
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node


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

    def _assert_marked_sync_failed(self, saved_query_id: str) -> None:
        lineage_issue = Node.objects.get(saved_query_id=saved_query_id).lineage_issue
        assert lineage_issue is not None
        self.assertEqual(lineage_issue["kind"], "sync_failed")

    @parameterized.expand([("plain", {}), ("with_frequency", {"sync_frequency": "6hour"})])
    def test_create_gives_a_view_whose_dag_sync_fails_a_marked_node(self, _name: str, fields: dict[str, Any]) -> None:
        with patch("products.data_modeling.backend.facade.api.sync_saved_query_to_dag", side_effect=RuntimeError):
            response = self._create_view(**fields)
        self.assertEqual(response.status_code, 201, response.content)
        self._assert_marked_sync_failed(response.json()["id"])

    def test_update_keeps_a_query_whose_dag_sync_fails_and_marks_its_node(self) -> None:
        created = self._create_view().json()
        with patch("products.data_modeling.backend.facade.api.sync_saved_query_to_dag", side_effect=RuntimeError):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}",
                {
                    "query": {"kind": "HogQLQuery", "query": "select event from events LIMIT 7"},
                    "edited_history_id": created["latest_history_id"],
                },
            )
        self.assertEqual(response.status_code, 200, response.content)
        self._assert_marked_sync_failed(created["id"])

    def test_create_places_the_view_in_the_default_dag_with_its_cadence(self) -> None:
        other = DAG.objects.create(team=self.team, name="Other")
        response = self._create_view(dag_id=str(other.id), sync_frequency="6hour")
        self.assertEqual(response.status_code, 201, response.content)
        node = Node.objects.get(saved_query_id=response.json()["id"])
        self.assertEqual(node.dag_id, DAG.get_or_create_default(self.team).id)
        self.assertEqual(get_declared_target(node), timedelta(hours=6))

    def test_deleted_cannot_be_set_through_the_write_api(self) -> None:
        created = self._create_view().json()
        url = f"/api/environments/{self.team.id}/warehouse_saved_queries/{created['id']}"
        response = self.client.patch(url, {"deleted": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(DataWarehouseSavedQuery.objects.get(id=created["id"]).deleted)
        self.assertEqual(self.client.get(url).status_code, 200)

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
