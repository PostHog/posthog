from posthog.test.base import (
    APIBaseTest,
)
from unittest.mock import patch
from posthog.warehouse.models import DataWarehouseSavedQuery


class TestView(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/" + view["id"],
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_saved_queries/" + view_1["id"],
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select * from outer_event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(view_1_response.status_code, 400, view_1_response.content)

    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    @patch(
        "posthog.warehouse.models.datawarehouse_saved_query.DataWarehouseSavedQuery.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_view_with_external_table(self, patch_get_columns_1, patch_get_columns_2):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {"access_key": "_accesskey", "access_secret": "_accesssecret"},
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        response = response.json()

        view_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select id, a_column from whatever LIMIT 100",
                },
            },
        )
        self.assertEqual(view_1_response.status_code, 201, view_1_response.content)

        self.assertEqual(DataWarehouseSavedQuery.objects.all().count(), 1)

        response = self.client.delete(f"/api/projects/{self.team.id}/warehouse_tables/{response['id']}")

        self.assertEqual(DataWarehouseSavedQuery.objects.all().count(), 0)
