from posthog.test.base import (
    APIBaseTest,
)


class TestView(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view = response.json()
        self.assertEqual(view["name"], "event_view")
        self.assertEqual(view["columns"], [{"key": "event", "type": "string"}])

    def test_view_doesnt_exist(self):
        view_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(view_1_response.status_code, 400, view_1_response.content)

    def test_view_updated(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view = response.json()
        view_1_response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_saved_query/" + view["id"],
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select distinct_id from events LIMIT 100",
                },
            },
        )

        self.assertEqual(view_1_response.status_code, 200, view_1_response.content)
        view_1 = view_1_response.json()
        self.assertEqual(view_1["name"], "event_view")
        self.assertEqual(view_1["columns"], [{"key": "distinct_id", "type": "string"}])

    def test_circular_view(self):
        view_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from events LIMIT 100",
                },
            },
        )
        self.assertEqual(view_1_response.status_code, 201, view_1_response.content)
        view_1 = view_1_response.json()

        view_2_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_query/",
            {
                "name": "outer_event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(view_2_response.status_code, 201, view_2_response.content)

        view_1_response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_saved_query/" + view_1["id"],
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from outer_event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(view_1_response.status_code, 400, view_1_response.content)
