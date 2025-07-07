from posthog.test.base import APIBaseTest, FuzzyInt
from posthog.warehouse.models import DataWarehouseJoin, DataWarehouseTable
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource


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

    def test_reading_dot_notation(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSource.Type.STRIPE,
        )
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        warehouse_table = DataWarehouseTable.objects.create(
            name="stripe_table_1",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name="table_1",
            source=source,
            table=warehouse_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="stripe_table_1",
            joining_table_key="id",
            field_name="some_field",
            configuration=None,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/warehouse_view_links/")
        assert response.status_code == 200

        view_links = response.json()
        assert isinstance(view_links, dict)
        assert isinstance(view_links["results"], list)
        assert len(view_links["results"]) == 1

        view_link = view_links["results"][0]

        # Assert it gets returned with dot notation
        assert view_link["joining_table_name"] == "stripe.table_1"

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

    def test_field_name_periods(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "source_table_key": "uuid",
                "joining_table_key": "id",
                "field_name": "some_field.other.field",
                "configuration": None,
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

    def test_list(self):
        join1 = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person_field",
            configuration=None,
        )

        join2 = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="uuid",
            joining_table_name="groups",
            joining_table_key="group_id",
            field_name="group_field",
            configuration={"experiments_optimized": True},
        )

        join3 = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="id",
            joining_table_name="cohorts",
            joining_table_key="person_id",
            field_name="cohort_field",
            configuration=None,
        )

        # Test that listing joins uses efficient querying

        with self.assertNumQueries(
            FuzzyInt(16, 17)
        ):  # depends when team revenue analytisc config cache is hit in a test
            response = self.client.get(f"/api/environments/{self.team.id}/warehouse_view_links/")

        self.assertEqual(response.status_code, 200)

        view_links = response.json()
        self.assertIsInstance(view_links, dict)
        self.assertIn("results", view_links)
        self.assertIsInstance(view_links["results"], list)
        self.assertEqual(len(view_links["results"]), 3)

        # Verify the joins are returned with correct data
        join_ids = {join["id"] for join in view_links["results"]}
        expected_ids = {str(join1.id), str(join2.id), str(join3.id)}
        self.assertEqual(join_ids, expected_ids)
