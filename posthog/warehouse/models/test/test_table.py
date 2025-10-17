from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql.database.models import DateTimeDatabaseField, IntegerDatabaseField, StringDatabaseField

from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.models.table import SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING


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

    def test_get_columns_with_unknown_field(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Nothing"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Nothing", "hogql": "UnknownDatabaseField", "valid": True}}

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

    def test_get_columns_with_even_more_complex_tuples(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        clickhouse_type = "Tuple(data Tuple(`$event_schema` Tuple(version Nullable(String)), client_id Nullable(String), client_name Nullable(String), connection Nullable(String), connection_id Nullable(String), date Nullable(String), details Tuple(actions Tuple(executions Array(Nullable(String))), completedAt Nullable(Int64), elapsedTime Nullable(Int64), initiatedAt Nullable(Int64), prompts Array(Tuple(completedAt Nullable(Int64), connection Nullable(String), connection_id Nullable(String), elapsedTime Nullable(Int64), flow Nullable(String), identity Nullable(String), initiatedAt Nullable(Int64), name Nullable(String), stats Tuple(loginsCount Nullable(Int64)), strategy Nullable(String), timers Tuple(rules Nullable(Int64)), url Nullable(String), user_id Nullable(String), user_name Nullable(String))), session_id Nullable(String), stats Tuple(loginsCount Nullable(Int64))), hostname Nullable(String), ip Nullable(String), log_id Nullable(String), strategy Nullable(String), strategy_type Nullable(String), type Nullable(String), user_agent Nullable(String), user_id Nullable(String), user_name Nullable(String)), log_id Nullable(String))"

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", clickhouse_type]]
            columns = table.get_columns()
            assert columns == {
                "id": {
                    "clickhouse": clickhouse_type,
                    "hogql": "StringJSONDatabaseField",
                    "valid": True,
                }
            }

    def test_get_columns_with_hyphened_names(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("posthog.warehouse.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id-hype", "String"]]
            columns = table.get_columns()
            assert columns == {
                "id-hype": {
                    "clickhouse": "String",
                    "hogql": "StringDatabaseField",
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
                StringDatabaseField(name="id", nullable=False),
                DateTimeDatabaseField(name="timestamp", nullable=False),
                IntegerDatabaseField(name="mrr", nullable=True),
                IntegerDatabaseField(name="offset", nullable=False),
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
                StringDatabaseField(name="id", nullable=False),
                DateTimeDatabaseField(name="timestamp", nullable=False),
                IntegerDatabaseField(name="mrr", nullable=True),
                IntegerDatabaseField(name="offset", nullable=False),
            ],
        )

    def test_hogql_definition_column_name_hyphen(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp-dash": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
            },
            credential=credential,
        )

        assert list(table.hogql_definition().fields.keys()) == ["id", "timestamp-dash"]
        assert table.hogql_definition().structure == "`id` String, `timestamp-dash` DateTime64(3, 'UTC')"

    def test_complex_type_with_array_nested_datetime_fields(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/peter_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
                "nested": {
                    "clickhouse": "Array(Tuple(url Nullable(String), date Tuple(member0 Nullable(DateTime64(6, 'UTC')), member1 Nullable(String)), text Nullable(String), type Nullable(String), email Nullable(String), field Tuple(id Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))), choice Tuple(id Nullable(String), label Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))), number Nullable(Float64), boolean Nullable(Bool), choices Tuple(ids Array(Nullable(String)), labels Array(Nullable(String)), _airbyte_additional_properties Map(String, Nullable(String))), payment Tuple(name Nullable(String), last4 Nullable(String), amount Nullable(String), success Nullable(Bool), _airbyte_additional_properties Map(String, Nullable(String))), file_url Nullable(String), phone_number Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))))",
                    "hogql": "StringArrayDatabaseField",
                    "valid": True,
                },
            },
            credential=credential,
        )

        definition = table.hogql_definition()
        assert len(definition.fields) == 2
        assert (
            definition.structure
            == "`id` Nullable(String), `nested` Array(Tuple( Nullable(String),  Tuple( Nullable(DateTime64(6, 'UTC')),  Nullable(String)),  Nullable(String),  Nullable(String),  Nullable(String),  Tuple( Nullable(String),  Map(String, Nullable(String))),  Tuple( Nullable(String),  Nullable(String),  Map(String, Nullable(String))),  Nullable(Float64),  Nullable(Bool),  Tuple( Array(Nullable(String)),  Array(Nullable(String)),  Map(String, Nullable(String))),  Tuple( Nullable(String),  Nullable(String),  Nullable(String),  Nullable(Bool),  Map(String, Nullable(String))),  Nullable(String),  Nullable(String),  Map(String, Nullable(String))))"
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
            "`id` String, `timestamp` DateTime64(3, 'UTC'), `mrr` Nullable(Int64), `complex_field` Array(Tuple( Nullable(String),  Nullable(String),  Map(String, Nullable(String)))), `tuple_field` Tuple(type Nullable(String), value Nullable(String), _airbyte_additional_properties Map(String, Nullable(String))), `offset` UInt32",
        )

    def test_hogql_definition_nullable(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "mrr": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
            },
            credential=credential,
        )
        self.assertEqual(
            list(table.hogql_definition().fields.keys()),
            ["id", "mrr"],
        )

        self.assertEqual(
            list(table.hogql_definition().fields.values()),
            [
                StringDatabaseField(name="id", nullable=False),
                IntegerDatabaseField(name="mrr", nullable=True),
            ],
        )

        self.assertEqual(
            table.hogql_definition().structure,
            "`id` String, `mrr` Nullable(Int64)",
        )

    def test_comprehensive_table_definition(self):
        base_columns = {
            "int64": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
            "float64": {"clickhouse": "Float64", "hogql": "FloatDatabaseField"},
            "decimal": {"clickhouse": "Decimal(10, 2)", "hogql": "DecimalDatabaseField"},
            "string": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            "datetime": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
            "date": {"clickhouse": "Date", "hogql": "DateDatabaseField"},
            "boolean": {"clickhouse": "Bool", "hogql": "BooleanDatabaseField"},
            "array": {"clickhouse": "Array(String)", "hogql": "StringArrayDatabaseField"},
            "map": {"clickhouse": "Map(String, String)", "hogql": "StringJSONDatabaseField"},
        }

        # Assert this is a comprehensive list of all possible ClickHouse types
        assert len({val["clickhouse"] for key, val in base_columns.items()}) == len(
            SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING
        )

        # Create a nullable copy for each of the above
        nullable_columns = {
            f"{key}_nullable": {"clickhouse": f"Nullable({val['clickhouse']})", "hogql": val["hogql"]}
            for key, val in base_columns.items()
        }

        # Merge the two dictionaries
        columns = {**base_columns, **nullable_columns}

        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns=columns,
            credential=credential,
        )

        definition = table.hogql_definition()
        assert len(definition.fields) == len(columns)
        assert (
            definition.structure == "`int64` Int64, `float64` Float64, `decimal` Decimal(10, 2), "
            "`string` String, `datetime` DateTime64(3, 'UTC'), `date` Date, "
            "`boolean` Bool, `array` Array(String), `map` Map(String, String), "
            "`int64_nullable` Nullable(Int64), `float64_nullable` Nullable(Float64), "
            "`decimal_nullable` Nullable(Decimal(10, 2)), `string_nullable` Nullable(String), "
            "`datetime_nullable` Nullable(DateTime64(3, 'UTC')), `date_nullable` Nullable(Date), "
            "`boolean_nullable` Nullable(Bool), `array_nullable` Nullable(Array(String)), "
            "`map_nullable` Nullable(Map(String, String))"
        )

    def assert_raises_with_invalid_hog_column_type(self, column_type):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": column_type, "hogql": "RandomUnknownDatabaseField"},
            },
            credential=credential,
        )

        with self.assertRaises(Exception):
            table.hogql_definition()
