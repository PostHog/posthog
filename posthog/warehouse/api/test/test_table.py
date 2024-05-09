from unittest.mock import patch

from clickhouse_driver.errors import ServerException

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseTable
from posthog.warehouse.models.external_data_source import ExternalDataSource


class TestTable(APIBaseTest):
    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_create(self, patch_get_columns):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        response = response.json()

        table = DataWarehouseTable.objects.get(id=response["id"])
        credentials = table.credential

        self.assertEqual(table.name, "whatever")
        self.assertEqual(table.columns, {"id": "String", "a_column": "String"})
        self.assertEqual(credentials.access_key, "_accesskey")
        self.assertEqual(credentials.access_secret, "_accesssecret")

    @patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns")
    def test_credentialerror(self, patch_get_columns):
        patch_get_columns.side_effect = ServerException(
            message="""DB::Exception: The AWS Access Key Id you provided does not exist in our records.: Cannot extract table structure from Parquet format file. You can specify the structure manually. Stack trace:\n\n0. DB::Exception::Exception(std::__1::basic_string<char, std::__1::char_traits<char>, std::__1::allocator<char> > const&, int, bool) @ 0x8e25488 in /u""",
            code=499,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()

    def test_update_schema_200_old_column_style(self):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={"id": "Nullable(Int64)"}
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns["id"] == {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField"}

    def test_update_schema_200_new_column_style(self):
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns={"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}},
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns["id"] == {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField"}

    def test_update_schema_200_no_updates(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns == columns

        response = self.client.post(f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {})

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns == columns

    def test_update_schema_400_with_source(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        souce = ExternalDataSource.objects.create(team=self.team, team_id=self.team.pk)
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
            external_data_source_id=souce.pk,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "The table must be a manually linked table"
        assert table.columns == columns

    def test_update_schema_400_with_non_existing_column(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema",
            {"updates": {"some_other_column": "float"}},
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "Column some_other_column does not exist on table"
        assert table.columns == columns

    def test_update_schema_400_with_invalid_type(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema",
            {"updates": {"id": "another_type"}},
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "Can not parse type another_type for column id - type does not exist"
        assert table.columns == columns
