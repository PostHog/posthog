from posthog.test.base import (
    APIBaseTest,
)

from posthog.models import PropertyDefinition


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
            {"saved_query_id": saved_query["id"], "table": 1, "join_key": "distinct_id"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()

        self.assertEqual(view_link["saved_query"], saved_query["id"])
        self.assertEqual(len(PropertyDefinition.objects.all()), 2)
