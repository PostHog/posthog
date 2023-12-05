from posthog.api.services.query import process_query
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseSavedQuery, DataWarehouseViewLink


class TestViewLinkQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "saved_query_id": saved_query["id"],
                "table": "events",
                "to_join_key": "distinct_id",
                "from_join_key": "distinct_id",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()

        self.assertEqual(view_link["saved_query"], saved_query["id"])

    def test_create_key_error(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "saved_query_id": saved_query["id"],
                "table": "eventss",
                "to_join_key": "distinct_id",
                "from_join_key": "distinct_id",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "saved_query_id": saved_query["id"],
                "table": "events",
                "to_join_key": "distinct_id",
                "from_join_key": "key_that_doesnt_exist",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_create_saved_query_key_error(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "saved_query_id": saved_query["id"],
                "table": "eventss",
                "to_join_key": "key_that_doesn't_exist",
                "from_join_key": "distinct_id",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_view_link_columns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            saved_query=saved_query,
            table="events",
            to_join_key="distinct_id",
            team=self.team,
            from_join_key="distinct_id",
        )

        query_response = process_query(
            team=self.team,
            query_json={
                "kind": "DatabaseSchemaQuery",
            },
        )
        self.assertIn(
            {
                "key": "event_view",
                "type": "view",
                "table": "event_view",
                "fields": ["fake"],
            },
            query_response["events"],
        )

    def test_view_link_columns_query(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select distinct_id AS fake from events LIMIT 100",
                },
            },
        )
        saved_query_response = response.json()
        saved_query = DataWarehouseSavedQuery.objects.get(pk=saved_query_response["id"])

        DataWarehouseViewLink.objects.create(
            saved_query=saved_query,
            table="events",
            to_join_key="fake",
            from_join_key="distinct_id",
            team=self.team,
        )

        query_response = process_query(
            team=self.team,
            query_json={
                "kind": "HogQLQuery",
                "query": f"SELECT event_view.fake FROM events",
            },
        )
        self.assertEqual(query_response["types"], [("fake", "String")])

    def test_view_link_nested_multiple_joins(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select distinct_id AS fake from events LIMIT 100",
                },
            },
        )
        saved_query_response = response.json()
        saved_query = DataWarehouseSavedQuery.objects.get(pk=saved_query_response["id"])

        DataWarehouseViewLink.objects.create(
            saved_query=saved_query,
            table="events",
            to_join_key="fake",
            from_join_key="distinct_id",
            team=self.team,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "person_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event AS p_distinct_id from events",
                },
            },
        )
        saved_query_response = response.json()
        saved_query = DataWarehouseSavedQuery.objects.get(pk=saved_query_response["id"])

        DataWarehouseViewLink.objects.create(
            saved_query=saved_query,
            table="events",
            to_join_key="p_distinct_id",
            from_join_key="distinct_id",
            team=self.team,
        )

        query_response = process_query(
            team=self.team,
            query_json={
                "kind": "HogQLQuery",
                "query": f"SELECT event_view.fake, person_view.p_distinct_id FROM events",
            },
        )

        self.assertEqual(
            query_response["types"],
            [
                ("events__event_view.fake", "String"),
                ("events__person_view.p_distinct_id", "String"),
            ],
        )

    def test_delete(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "saved_query_id": saved_query["id"],
                "table": "events",
                "to_join_key": "distinct_id",
                "from_join_key": "distinct_id",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()

        self.assertEqual(view_link["saved_query"], saved_query["id"])

        response = self.client.delete(f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query['id']}")
        self.assertEqual(response.status_code, 204, response.content)

        self.assertEqual(DataWarehouseViewLink.objects.all().count(), 0)
