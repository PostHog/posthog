from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseJoin


class TestViewLinkQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_key_error(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "eventssss",
                "joining_table_name": "persons",
                "source_table_key": "key_that_doesnt_exist",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_create_saved_query_key_error(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "eventssss",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_create_saved_query_join_key_function(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "upper(uuid)",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_delete(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()

        response = self.client.delete(f"/api/projects/{self.team.id}/warehouse_view_links/{view_link['id']}")
        self.assertEqual(response.status_code, 204, response.content)

        self.assertEqual(DataWarehouseJoin.objects.all().count(), 0)
