from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseJoin


class TestViewLinkQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field",
                "configuration": None,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()
        self.assertEqual(
            view_link,
            {
                "id": view_link["id"],
                "deleted": False,
                "created_by": view_link["created_by"],
                "created_at": view_link["created_at"],
                "source_table_name": "events",
                "source_table_key": "uuid",
                "joining_table_name": "persons",
                "joining_table_key": "id",
                "field_name": "some_field",
                "configuration": None,
            },
        )

    def test_create_with_configuration(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field",
                "configuration": {"experiments_optimized": True, "experiments_timestamp_key": "timestamp"},
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        view_link = response.json()
        self.assertEqual(
            view_link,
            {
                "id": view_link["id"],
                "deleted": False,
                "created_by": view_link["created_by"],
                "created_at": view_link["created_at"],
                "source_table_name": "events",
                "source_table_key": "uuid",
                "joining_table_name": "persons",
                "joining_table_key": "id",
                "field_name": "some_field",
                "configuration": {"experiments_optimized": True, "experiments_timestamp_key": "timestamp"},
            },
        )

    def test_create_key_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/",
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
            f"/api/environments/{self.team.id}/warehouse_view_links/",
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
            f"/api/environments/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "upper(uuid)",
                "joining_table_key": "id",
                "field_name": "some_field",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_update_with_configuration(self):
        join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="some_field",
            configuration=None,
        )
        join.save()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_view_links/{join.id}/",
            {"configuration": {"experiments_optimized": True, "experiments_timestamp_key": "timestamp"}},
        )
        self.assertEqual(response.status_code, 200, response.content)
        view_link = response.json()
        self.assertEqual(
            view_link,
            {
                "id": view_link["id"],
                "deleted": False,
                "created_by": view_link["created_by"],
                "created_at": view_link["created_at"],
                "source_table_name": "events",
                "source_table_key": "distinct_id",
                "joining_table_name": "persons",
                "joining_table_key": "id",
                "field_name": "some_field",
                "configuration": {"experiments_optimized": True, "experiments_timestamp_key": "timestamp"},
            },
        )
        join.refresh_from_db()
        self.assertEqual(join.configuration, {"experiments_optimized": True, "experiments_timestamp_key": "timestamp"})

    def test_delete(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/",
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

        response = self.client.delete(f"/api/environments/{self.team.id}/warehouse_view_links/{view_link['id']}")
        self.assertEqual(response.status_code, 204, response.content)

        self.assertEqual(DataWarehouseJoin.objects.all().count(), 0)
