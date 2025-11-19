import re
from textwrap import dedent

from posthog.test.base import APIBaseTest, FuzzyInt
from unittest.mock import patch

from rest_framework import status

from posthog.schema import HogQLQueryResponse

from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.models import DataWarehouseJoin, DataWarehouseTable
from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


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
            source_type=ExternalDataSourceType.STRIPE,
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
            FuzzyInt(18, 19)
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


def _mock_execute_hogql_side_effect(*args, **kwargs):
    """Helper to minimize side effects of mocking, just avoiding the query execution itself."""
    executor = HogQLQueryExecutor(*args, **kwargs)
    executor.generate_clickhouse_sql()
    return HogQLQueryResponse(
        query=executor.query,
        hogql=executor.hogql,
        clickhouse=executor.clickhouse_sql,
        error=executor.error,
        timings=executor.timings.to_list(),
        results=[("foo", "bar")],
        columns=executor.print_columns,
        types=executor.types,
        modifiers=executor.query_modifiers,
        explain=executor.explain,
        metadata=executor.metadata,
    )


class TestViewLinkValidation(APIBaseTest):
    PATH = "products.data_warehouse.backend.api.view_link"

    def assertHogQLEqual(self, result, expected):
        formatted_result = dedent(re.sub(r"\s+", " ", result.strip())).strip()
        self.assertEqual(formatted_result, expected)

    def _create_external_source_table(self, prefix, table_name):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="postgres_source",
            connection_id="postgres_connection",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix=prefix,
        )

        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )

        warehouse_table = DataWarehouseTable.objects.create(
            name=table_name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=credentials,
            url_pattern="s3://bucket/user/*",
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
                "email": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            name=table_name,
            source=source,
            table=warehouse_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_basic_success(self, _):
        payloads = [
            (
                "string joining key",
                {
                    "source_table_name": "events",
                    "source_table_key": "uuid",
                    "joining_table_name": "persons",
                    "joining_table_key": "id",
                },
            ),
            (
                "integer joining key",
                {
                    "source_table_name": "groups",
                    "source_table_key": "index",
                    "joining_table_name": "system.feature_flags",
                    "joining_table_key": "id",
                },
            ),
        ]
        for msg, payload in payloads:
            with self.subTest(msg=msg):
                response = self.client.post(f"/api/environments/{self.team.id}/warehouse_view_links/validate/", payload)

                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
                data = response.json()
                self.assertTrue(data["is_valid"])
                self.assertIsNone(data["msg"])
                self.assertHogQLEqual(
                    data["hogql"],
                    f"SELECT validation.{payload['joining_table_key']} FROM {payload['source_table_name']} LIMIT 10",
                )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_system_table_success(self, _):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "groups",
                "source_table_key": "index",
                "joining_table_name": "system.group_type_mappings",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.id FROM groups LIMIT 10",
        )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_dot_notation_table_name(self, _):
        self._create_external_source_table(prefix="foo", table_name="bar")

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "postgres.foo.bar",
                "source_table_key": "id",
                "joining_table_name": "events",
                "joining_table_key": "distinct_id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.distinct_id FROM `postgres.foo.bar` AS postgres__foo__bar LIMIT 10",
        )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_hogql_expression_keys(self, _):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "upper(distinct_id)",
                "joining_table_name": "persons",
                "joining_table_key": "upper(id)",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.id FROM events LIMIT 10",
        )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_complex_expression(self, _):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "toString(distinct_id)",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.id FROM events LIMIT 10",
        )

    def test_nonexistent_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "nonexistent_field",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["attr"], None)
        self.assertEqual(data["code"], "QueryError")
        self.assertEqual(data["detail"], "Field not found: nonexistent_field")
        self.assertEqual(data["type"], "query_error")
        self.assertEqual(data["hogql"], "SELECT validation.id FROM events LIMIT 10")

    def test_invalid_source_table(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "nonexistent_table_xyz",
                "source_table_key": "id",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], None)
        self.assertEqual(data["code"], "invalid_input")
        self.assertEqual(data["detail"], "Invalid table: nonexistent_table_xyz")
        self.assertEqual(data["type"], "validation_error")

    def test_invalid_joining_table(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "distinct_id",
                "joining_table_name": "nonexistent_table_xyz",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], None)
        self.assertEqual(data["code"], "invalid_input")
        self.assertEqual(data["detail"], "Invalid table: nonexistent_table_xyz")
        self.assertEqual(data["type"], "validation_error")

    def test_invalid_expression(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "invalid syntax here !!@#",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], None)
        self.assertEqual(data["code"], "invalid_input")
        self.assertEqual(data["detail"], "mismatched input 'syntax' expecting <EOF>")
        self.assertEqual(data["type"], "validation_error")

    def test_missing_source_table_name(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_key": "distinct_id",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], "source_table_name")
        self.assertEqual(data["code"], "required")
        self.assertEqual(data["detail"], "This field is required.")
        self.assertEqual(data["type"], "validation_error")

    def test_missing_source_table_key(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "joining_table_name": "persons",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], "source_table_key")
        self.assertEqual(data["code"], "required")
        self.assertEqual(data["detail"], "This field is required.")
        self.assertEqual(data["type"], "validation_error")

    def test_missing_joining_table_name(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "distinct_id",
                "joining_table_key": "id",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], "joining_table_name")
        self.assertEqual(data["code"], "required")
        self.assertEqual(data["detail"], "This field is required.")
        self.assertEqual(data["type"], "validation_error")

    def test_missing_joining_table_key(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "distinct_id",
                "joining_table_name": "persons",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["attr"], "joining_table_key")
        self.assertEqual(data["code"], "required")
        self.assertEqual(data["detail"], "This field is required.")
        self.assertEqual(data["type"], "validation_error")

    def test_with_type_mismatch_warning(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "events",
                "source_table_key": "timestamp",  # DateTime field
                "joining_table_name": "persons",
                "joining_table_key": "id",  # String field
            },
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        data = response.json()
        self.assertEqual(data["attr"], None)
        self.assertEqual(data["code"], "CHQueryErrorIllegalTypeOfArgument")
        self.assertTrue(data["detail"].startswith("Illegal types of arguments (DateTime64(6, 'UTC'), UUID)"))
        self.assertEqual(data["type"], "query_error")
        self.assertEqual(data["hogql"], "SELECT validation.id FROM events LIMIT 10")

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_ambiguous_keys(self, _):
        self._create_external_source_table(prefix="test", table_name="foo")
        self._create_external_source_table(prefix="test", table_name="bar")

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "postgres.test.foo",
                "source_table_key": "email",
                "joining_table_name": "postgres.test.bar",
                "joining_table_key": "email",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.email FROM `postgres.test.foo` AS postgres__test__foo LIMIT 10",
        )

    @patch(f"{PATH}.execute_hogql_query", side_effect=_mock_execute_hogql_side_effect)
    def test_expression_with_dot_notation_table(self, _):
        self._create_external_source_table(prefix="test", table_name="user")
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_view_links/validate/",
            {
                "source_table_name": "postgres.test.user",
                "source_table_key": "lower(email)",
                "joining_table_name": "events",
                "joining_table_key": "lower(distinct_id)",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertTrue(data["is_valid"])
        self.assertIsNone(data["msg"])
        self.assertHogQLEqual(
            data["hogql"],
            "SELECT validation.distinct_id FROM `postgres.test.user` AS postgres__test__user LIMIT 10",
        )
