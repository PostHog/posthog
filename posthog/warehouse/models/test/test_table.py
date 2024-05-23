from unittest.mock import patch

from posthog.hogql.database.models import DateTimeDatabaseField, IntegerDatabaseField, StringDatabaseField
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable


class TestTable(BaseTest):
    def test_get_columns(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Int64"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True}}

    def test_get_columns_with_nullable(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Nullable(Int64)"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True}}

    def test_get_columns_with_type_args(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "DateTime(6, 'UTC')"]]
            columns = table.get_columns()
            assert columns == {
                "id": {"clickhouse": "DateTime(6, 'UTC')", "hogql": "DateTimeDatabaseField", "valid": True}
            }

    def test_get_columns_with_array(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Array(String)"]]
            columns = table.get_columns()
            assert columns == {
                "id": {"clickhouse": "Array(String)", "hogql": "StringArrayDatabaseField", "valid": True}
            }

    def test_get_columns_with_nullable_and_args(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Nullable(DateTime(6, 'UTC'))"]]
            columns = table.get_columns()
            assert columns == {
                "id": {"clickhouse": "Nullable(DateTime(6, 'UTC'))", "hogql": "DateTimeDatabaseField", "valid": True}
            }

    def test_get_columns_with_complex_tuples(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Map(String, Map(String, Array(UInt64)))"]]
            columns = table.get_columns()
            assert columns == {
                "id": {
                    "clickhouse": "Map(String, Map(String, Array(UInt64)))",
                    "hogql": "StringJSONDatabaseField",
                    "valid": True,
                }
            }

    def test_hogql_definition_old_style(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": "String",
                "timestamp": "DateTime64(3, 'UTC')",
                "mrr": "Nullable(Int64)",
                "offset": "UInt32",
            },
            credential=credential,
        )
        self.assertEqual(
            list(table.hogql_definition().fields.keys()),
            ["id", "timestamp", "mrr", "offset"],
        )

        self.assertEqual(
            list(table.hogql_definition().fields.values()),
            [
                StringDatabaseField(name="id"),
                DateTimeDatabaseField(name="timestamp"),
                IntegerDatabaseField(name="mrr"),
                IntegerDatabaseField(name="offset"),
            ],
        )

    def test_hogql_definition_new_style(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                "mrr": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
                "offset": {"clickhouse": "UInt32", "hogql": "IntegerDatabaseField"},
            },
            credential=credential,
        )
        self.assertEqual(
            list(table.hogql_definition().fields.keys()),
            ["id", "timestamp", "mrr", "offset"],
        )

        self.assertEqual(
            list(table.hogql_definition().fields.values()),
            [
                StringDatabaseField(name="id"),
                DateTimeDatabaseField(name="timestamp"),
                IntegerDatabaseField(name="mrr"),
                IntegerDatabaseField(name="offset"),
            ],
        )

    def test_hogql_definition_tuple_patch(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": "String",
                "timestamp": "DateTime64(3, 'UTC')",
                "mrr": "Nullable(Int64)",
                "complex_field": "Array(Tuple(type Nullable(String), value Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))))",
                "tuple_field": "Tuple(type Nullable(String), value Nullable(String), _airbyte_additional_properties Map(String, Nullable(String)))",
                "offset": "UInt32",
            },
            credential=credential,
        )
        self.assertEqual(
            list(table.hogql_definition().fields.keys()),
            ["id", "timestamp", "mrr", "complex_field", "tuple_field", "offset"],
        )
        self.assertEqual(
            table.hogql_definition().structure,
            "id String, timestamp DateTime64(3, 'UTC'), mrr Int64, complex_field Array(Tuple( Nullable(String),  Nullable(String),  Map(String, Nullable(String)))), tuple_field Tuple(type Nullable(String), value Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))), offset UInt32",
        )
