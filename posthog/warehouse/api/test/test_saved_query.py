from posthog.test.base import (
    APIBaseTest,
)


class TestSavedQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query = response.json()
        self.assertEqual(saved_query["name"], "event_view")
        self.assertEqual(saved_query["columns"], {"event": "String"})

    def test_saved_query_doesnt_exist(self):
        saved_query_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_query_1_response.status_code, 400, saved_query_1_response.content)

    def test_view_updated(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query_1_response = response.json()
        saved_query_1_response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_view/" + saved_query_1_response["id"],
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select distinct_id from events LIMIT 100",
                },
            },
        )

        self.assertEqual(saved_query_1_response.status_code, 200, saved_query_1_response.content)
        view_1 = saved_query_1_response.json()
        self.assertEqual(view_1["name"], "event_view")
        self.assertEqual(view_1["columns"], {"distinct_id": "String"})

    def test_circular_view(self):
        saved_query_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from events LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_query_1_response.status_code, 201, saved_query_1_response.content)
        saved_query_1 = saved_query_1_response.json()

        saved_view_2_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view/",
            {
                "name": "outer_event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_view_2_response.status_code, 201, saved_view_2_response.content)

        saved_view_1_response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_view/" + saved_query_1["id"],
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from outer_event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_view_1_response.status_code, 400, saved_view_1_response.content)
