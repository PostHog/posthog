import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StructDatabaseField,
)
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError

from products.data_warehouse.backend.direct_postgres import (
    DIRECT_POSTGRES_CATALOG_OPTION,
    DIRECT_POSTGRES_SCHEMA_OPTION,
    DIRECT_POSTGRES_TABLE_OPTION,
)
from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseTable
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING
from products.data_warehouse.backend.models.util import postgres_column_to_dwh_column
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestTable(BaseTest):
    @parameterized.expand(
        [
            ("lowercase", "posthog_dashboard"),
            ("mixed_case", "Accounts"),
        ]
    )
    def test_direct_postgres_table_uses_schema_name(self, _name: str, table_name: str):
        source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix="Readable Name",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        table = DataWarehouseTable.objects.create(
            name=table_name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
        )

        definition = table.hogql_definition()

        assert isinstance(definition, DirectPostgresTable)
        assert definition.postgres_table_name == table_name

    def test_direct_postgres_table_uses_physical_schema_and_table_options(self):
        source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix="Readable Name",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"schema": ""},
        )
        table = DataWarehouseTable.objects.create(
            name="public.accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            options={
                DIRECT_POSTGRES_SCHEMA_OPTION: "public",
                DIRECT_POSTGRES_TABLE_OPTION: "accounts",
            },
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
        )

        definition = table.hogql_definition()

        assert isinstance(definition, DirectPostgresTable)
        assert definition.name == "public.accounts"
        assert definition.postgres_schema == "public"
        assert definition.postgres_table_name == "accounts"

    def test_direct_postgres_table_supports_catalog_options(self):
        source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix="Readable Name",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"schema": ""},
        )
        table = DataWarehouseTable.objects.create(
            name="system.query_log",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            options={
                DIRECT_POSTGRES_CATALOG_OPTION: "ducklake",
                DIRECT_POSTGRES_SCHEMA_OPTION: "system",
                DIRECT_POSTGRES_TABLE_OPTION: "query_log",
            },
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
        )

        definition = table.hogql_definition()

        assert isinstance(definition, DirectPostgresTable)
        assert definition.postgres_catalog == "ducklake"
        assert definition.to_printed_postgres(context=None) == "ducklake.system.query_log"

    def test_direct_postgres_table_cannot_be_printed_to_clickhouse(self):
        source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix="Readable Name",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
        )

        definition = table.hogql_definition()

        with pytest.raises(QueryError, match="Direct Postgres tables cannot be printed into ClickHouse SQL"):
            definition.to_printed_clickhouse(context=None)

    def test_postgres_column_to_dwh_column_supports_struct_types(self):
        column = postgres_column_to_dwh_column(
            "membership",
            'STRUCT("type" VARCHAR, tier VARCHAR, frequency VARCHAR, provider VARCHAR)',
            False,
        )

        assert column == {
            "clickhouse": "Tuple(String, String, String, String)",
            "hogql": "StructDatabaseField",
            "valid": True,
            "fields": {
                "type": {"clickhouse": "String", "hogql": "string", "valid": True},
                "tier": {"clickhouse": "String", "hogql": "string", "valid": True},
                "frequency": {"clickhouse": "String", "hogql": "string", "valid": True},
                "provider": {"clickhouse": "String", "hogql": "string", "valid": True},
            },
        }

    def test_direct_postgres_table_supports_struct_columns(self):
        source = ExternalDataSource.objects.create(
            source_id="source-id",
            connection_id="connection-id",
            destination_id="destination-id",
            team=self.team,
            sync_frequency=ExternalDataSource.SyncFrequency.DAILY,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            prefix="Readable Name",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            columns={
                "membership": {
                    "clickhouse": "Tuple(String, String, String, String)",
                    "hogql": "StructDatabaseField",
                    "fields": {
                        "type": {"clickhouse": "String", "hogql": "string", "valid": True},
                        "tier": {"clickhouse": "String", "hogql": "string", "valid": True},
                        "frequency": {"clickhouse": "String", "hogql": "string", "valid": True},
                        "provider": {"clickhouse": "String", "hogql": "string", "valid": True},
                    },
                }
            },
        )

        definition = table.hogql_definition()

        assert isinstance(definition, DirectPostgresTable)
        assert isinstance(definition.fields["membership"], StructDatabaseField)
        assert set(definition.fields["membership"].fields.keys()) == {"type", "tier", "frequency", "provider"}

    def test_get_columns(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Int64"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True}}

    def test_get_columns_with_nullable(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Nullable(Int64)"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True}}

    def test_get_columns_with_unknown_field(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
            sync_execute_results.return_value = [["id", "Nothing"]]
            columns = table.get_columns()
            assert columns == {"id": {"clickhouse": "Nothing", "hogql": "UnknownDatabaseField", "valid": True}}

    def test_get_columns_with_type_args(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table", url_pattern="", credential=credential, format="Parquet", team=self.team
        )

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

        with patch("products.data_warehouse.backend.models.table.sync_execute") as sync_execute_results:
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

    def test_hogql_definition_new_style_with_lowercase_hogql_type(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="bla",
            url_pattern="https://databeach-hackathon.s3.amazonaws.com/tim_test/test_events6.pqt",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": {"clickhouse": "Int64", "hogql": "integer"},
            },
            credential=credential,
        )

        self.assertEqual(
            list(table.hogql_definition().fields.values()),
            [IntegerDatabaseField(name="id", nullable=False)],
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

        definition = table.hogql_definition()
        assert isinstance(definition, HogQLDataWarehouseTable)
        assert list(definition.fields.keys()) == ["id", "timestamp-dash"]
        assert definition.structure == "`id` String, `timestamp-dash` DateTime64(3, 'UTC')"

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
        assert isinstance(definition, HogQLDataWarehouseTable)
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
        definition = table.hogql_definition()
        assert isinstance(definition, HogQLDataWarehouseTable)
        self.assertEqual(
            list(definition.fields.keys()),
            ["id", "timestamp", "mrr", "complex_field", "tuple_field", "offset"],
        )
        self.assertEqual(
            definition.structure,
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
        definition = table.hogql_definition()
        assert isinstance(definition, HogQLDataWarehouseTable)
        self.assertEqual(
            list(definition.fields.keys()),
            ["id", "mrr"],
        )

        self.assertEqual(
            list(definition.fields.values()),
            [
                StringDatabaseField(name="id", nullable=False),
                IntegerDatabaseField(name="mrr", nullable=True),
            ],
        )

        self.assertEqual(
            definition.structure,
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
        assert isinstance(definition, HogQLDataWarehouseTable)
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

    def test_csv_allow_double_quotes_persisted_via_options(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_csv",
            url_pattern="https://example.com/test.csv",
            credential=credential,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            options={"csv_allow_double_quotes": False},
            team=self.team,
        )

        assert table.csv_allow_double_quotes is False
        table.refresh_from_db()
        assert table.csv_allow_double_quotes is False

    def test_csv_allow_double_quotes_defaults_to_none(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_csv",
            url_pattern="https://example.com/test.csv",
            credential=credential,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            team=self.team,
        )
        assert table.csv_allow_double_quotes is None

    @parameterized.expand([27, 117, 636])
    def test_validate_csv_double_quotes_raises_on_parse_failure(self, code):
        from clickhouse_driver.errors import ServerException

        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_csv",
            url_pattern="https://example.com/test.csv",
            credential=credential,
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            options={"csv_allow_double_quotes": True},
            team=self.team,
        )

        with patch(
            "products.data_warehouse.backend.models.table.sync_execute",
            side_effect=ServerException("Expected end of line", code=code),
        ):
            with pytest.raises(Exception, match="CSV parsing failed"):
                table._validate_csv_double_quotes_setting()

    def test_is_csv_format_for_non_csv(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_parquet",
            url_pattern="https://example.com/test.parquet",
            credential=credential,
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
        )
        assert table._is_csv_format() is False

    def test_is_csv_format_for_csv(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        with patch("products.data_warehouse.backend.models.table.sync_execute", return_value=[]):
            table = DataWarehouseTable.objects.create(
                name="test_csv",
                url_pattern="https://example.com/test.csv",
                credential=credential,
                format=DataWarehouseTable.TableFormat.CSV,
                team=self.team,
            )
        assert table._is_csv_format() is True

    def test_hogql_definition_sets_raw_settings_for_csv_with_double_quotes(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        with patch("products.data_warehouse.backend.models.table.sync_execute", return_value=[]):
            table = DataWarehouseTable.objects.create(
                name="rfc_csv",
                url_pattern="https://example.com/test.csv",
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                team=self.team,
                columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
                credential=credential,
            )
        # Simulate detection having found RFC 4180 quoting
        table.options["csv_allow_double_quotes"] = True
        table.save_base(raw=True)

        definition = table.hogql_definition()
        assert definition.top_level_settings is not None
        assert definition.top_level_settings.format_csv_allow_double_quotes is True

    def test_hogql_definition_sets_false_for_csv_with_none(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        with patch("products.data_warehouse.backend.models.table.sync_execute", return_value=[]):
            table = DataWarehouseTable.objects.create(
                name="legacy_csv",
                url_pattern="https://example.com/test.csv",
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                team=self.team,
                columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
                credential=credential,
            )
        # Simulate detection having returned None (both failed)
        table.options.pop("csv_allow_double_quotes", None)
        table.save_base(raw=True)

        definition = table.hogql_definition()
        assert definition.top_level_settings is not None
        assert definition.top_level_settings.format_csv_allow_double_quotes is False

    def test_hogql_definition_no_raw_settings_for_parquet(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="parquet_table",
            url_pattern="https://example.com/test.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
            credential=credential,
        )

        definition = table.hogql_definition()
        assert definition.top_level_settings is None

    def test_remove_named_tuples_backtick_quoted(self):
        from products.data_warehouse.backend.models.util import remove_named_tuples

        result = remove_named_tuples("Array(Tuple(`1` String, `2` String, `3` Nullable(String)))")
        assert result == "Array(Tuple( String,  String,  Nullable(String)))"

    def test_hogql_definition_tuple_with_backtick_positional_names(self):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table",
            url_pattern="https://example.com",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": "String",
                "deal_details": {
                    "clickhouse": "Array(Tuple(`1` String, `2` String, `3` Nullable(String)))",
                    "hogql": "StringArrayDatabaseField",
                    "valid": True,
                },
            },
            credential=credential,
        )
        definition = table.hogql_definition()
        assert isinstance(definition, HogQLDataWarehouseTable)
        assert definition.structure == "`id` String, `deal_details` Array(Tuple( String,  String,  Nullable(String)))"

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

    @parameterized.expand(
        [
            (
                "credential_error",
                "DB::Exception: The AWS Access Key Id you provided does not exist in our records.",
                499,
                "The Access Key you provided does not exist",
            ),
            (
                "archived_storage_class",
                "DB::Exception: The operation is not valid for the object's storage class. (S3_ERROR)",
                499,
                "Some files in the bucket are archived",
            ),
            (
                "access_denied",
                "DB::Exception: Access Denied: while reading key: some/path/file.parquet",
                499,
                "Access was denied when reading the provided file",
            ),
            (
                "no_such_bucket",
                "DB::Exception: S3 exception: `NoSuchBucket`, message: 'The specified bucket does not exist.'",
                499,
                "The provided bucket doesn't exist",
            ),
            (
                "empty_csv",
                "Cannot extract table structure from CSV format file, because there are no files with provided path in S3 or all files are empty",
                499,
                "The provided file doesn't exist in the bucket",
            ),
        ]
    )
    def test_safe_expose_ch_error(self, _name, error_message, error_code, expected_message):
        credential = DataWarehouseCredential.objects.create(access_key="test", access_secret="test", team=self.team)
        table = DataWarehouseTable.objects.create(
            name="test_table",
            url_pattern="https://example.com/test.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={"id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
            credential=credential,
        )

        with pytest.raises(Exception, match=expected_message):
            table._safe_expose_ch_error(ServerException(message=error_message, code=error_code))
