from posthog.test.base import (
    APIBaseTest,
)

from posthog.models import PropertyDefinition
from posthog.warehouse.models import DataWarehouseViewLink, DataWarehouseSavedQuery
from posthog.warehouse.query import get_view_link_columns
from posthog.api.query import process_query


class TestViewLinkQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event AS event, distinct_id as distinct_id from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query = response.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_link/",
            {"saved_query_id": saved_query["id"], "table": "events", "join_key": "distinct_id"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()

        self.assertEqual(view_link["saved_query"], saved_query["id"])
        self.assertEqual(len(PropertyDefinition.objects.all()), 2)

    def test_view_link_columns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event AS fake from events LIMIT 100",
                },
            },
        )
        saved_query_response = response.json()
        saved_query = DataWarehouseSavedQuery.objects.get(pk=saved_query_response["id"])

        DataWarehouseViewLink.objects.create(
            saved_query=saved_query, table="events", join_key="distinct_id", team=self.team
        )

        columns = get_view_link_columns(self.team)
        self.assertDictEqual(columns, {"events": [{"key": "fake", "type": "string"}]})

        response = process_query(
            team=self.team,
            query_json={
                "kind": "DatabaseSchemaQuery",
            },
        )
        self.assertIn({"key": "fake", "type": "string"}, response["events"])
