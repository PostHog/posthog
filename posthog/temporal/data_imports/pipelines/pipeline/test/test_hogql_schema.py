import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline_sync import merge_columns


class TestHogQLSchemaJsonDetection:
    @parameterized.expand(
        [
            ("json_object", ['{"key": "value"}', "other"], "StringJSONDatabaseField"),
            ("json_array", ["[1, 2, 3]", "other"], "StringJSONDatabaseField"),
            ("plain_string_first", ["plain text", '{"key": "value"}'], "StringDatabaseField"),
            ("null_then_json", [None, '{"key": "value"}'], "StringJSONDatabaseField"),
            ("all_nulls", [None, None], "StringDatabaseField"),
        ]
    )
    def test_json_detection_from_first_non_null_value(self, _name, values, expected_type):
        schema = HogQLSchema()
        table = pa.table({"col": pa.array(values, type=pa.string())})
        schema.add_pyarrow_table(table)
        assert schema.schema["col"] == expected_type


class TestAddPyarrowSchema:
    @parameterized.expand(
        [
            ("string", pa.string(), "StringDatabaseField"),
            ("int64", pa.int64(), "IntegerDatabaseField"),
            ("float64", pa.float64(), "FloatDatabaseField"),
            ("bool", pa.bool_(), "BooleanDatabaseField"),
            ("timestamp_us", pa.timestamp("us"), "DateTimeDatabaseField"),
            ("date32", pa.date32(), "DateDatabaseField"),
            ("decimal128", pa.decimal128(10, 2), "FloatDatabaseField"),
        ]
    )
    def test_maps_arrow_type(self, _name: str, arrow_type: pa.DataType, expected: str):
        schema = HogQLSchema()
        fields: list[pa.Field] = [pa.field("col", arrow_type)]
        schema.add_pyarrow_schema(pa.schema(fields))
        assert schema.schema["col"] == expected

    def test_skips_binary_fields(self):
        arrow_schema = pa.schema([pa.field("bin_col", pa.binary())])
        schema = HogQLSchema()
        schema.add_pyarrow_schema(arrow_schema)

        assert "bin_col" not in schema.schema

    def test_does_not_overwrite_non_string_types(self):
        schema = HogQLSchema()
        table = pa.table({"col": pa.array([1, 2], type=pa.int64())})
        schema.add_pyarrow_table(table)

        # Schema from a different batch has the same column as string
        arrow_schema = pa.schema([pa.field("col", pa.string())])
        schema.add_pyarrow_schema(arrow_schema)

        assert schema.schema["col"] == "IntegerDatabaseField"

    def test_add_pyarrow_table_upgrades_string_to_json(self):
        arrow_schema = pa.schema([pa.field("col", pa.string())])
        schema = HogQLSchema()
        schema.add_pyarrow_schema(arrow_schema)
        assert schema.schema["col"] == "StringDatabaseField"

        table = pa.table({"col": pa.array(['{"key": "value"}'], type=pa.string())})
        schema.add_pyarrow_table(table)
        assert schema.schema["col"] == "StringJSONDatabaseField"

    def test_covers_columns_missing_from_batch(self):
        fields: list[pa.Field] = [
            pa.field("col_a", pa.string()),
            pa.field("col_b", pa.int64()),
            pa.field("col_c", pa.float64()),
        ]
        arrow_schema = pa.schema(fields)
        table = pa.table({"col_a": pa.array(["hello"], type=pa.string())})

        schema = HogQLSchema()
        schema.add_pyarrow_schema(arrow_schema)
        schema.add_pyarrow_table(table)

        assert "col_a" in schema.schema
        assert "col_b" in schema.schema
        assert "col_c" in schema.schema
        assert schema.schema["col_b"] == "IntegerDatabaseField"
        assert schema.schema["col_c"] == "FloatDatabaseField"


class TestMergeColumnsJsonPreservation:
    @parameterized.expand(
        [
            (
                "preserves_json_when_new_batch_has_nulls",
                {"col": {"clickhouse": "String", "hogql": "StringJSONDatabaseField"}},
                {"col": "StringDatabaseField"},
                "StringJSONDatabaseField",
            ),
            (
                "keeps_string_when_no_prior_json",
                {"col": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
                {"col": "StringDatabaseField"},
                "StringDatabaseField",
            ),
            (
                "allows_upgrade_to_json",
                {"col": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
                {"col": "StringJSONDatabaseField"},
                "StringJSONDatabaseField",
            ),
            (
                "preserves_json_on_first_sync",
                {},
                {"col": "StringJSONDatabaseField"},
                "StringJSONDatabaseField",
            ),
        ]
    )
    def test_merge_columns_json_type_handling(self, _name, existing_columns, table_schema_dict, expected_hogql):
        db_columns = {"col": "String"}

        result = merge_columns(db_columns, table_schema_dict, existing_columns)

        assert result["col"]["hogql"] == expected_hogql
        assert result["col"]["clickhouse"] == "String"


class TestMergeColumnsRaceCondition:
    def test_merge_columns_preserves_existing_when_db_columns_incomplete(self):
        existing_columns = {
            "size_range": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
        }
        db_columns = {"user_id": "String"}
        table_schema = {"user_id": "StringDatabaseField"}

        result = merge_columns(db_columns, table_schema, existing_columns)

        assert "user_id" in result
        assert "size_range" in result
        assert result["size_range"] == {"clickhouse": "String", "hogql": "StringDatabaseField"}

    def test_merge_columns_preserves_all_when_db_columns_empty(self):
        existing_columns = {
            "size_range": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
        }
        db_columns: dict[str, str] = {}
        table_schema: dict[str, str] = {}

        result = merge_columns(db_columns, table_schema, existing_columns)

        assert result == existing_columns

    def test_merge_columns_updates_existing_column_types(self):
        existing_columns = {
            "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
        }
        db_columns = {"user_id": "Int64"}
        table_schema = {"user_id": "IntegerDatabaseField"}

        result = merge_columns(db_columns, table_schema, existing_columns)

        assert result["user_id"] == {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}

    def test_merge_columns_skips_column_when_hogql_type_missing_from_schema(self):
        existing_columns = {
            "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
        }
        db_columns = {"user_id": "String", "new_col": "Int64"}
        table_schema = {"user_id": "StringDatabaseField"}

        result = merge_columns(db_columns, table_schema, existing_columns)

        assert "user_id" in result
        assert "new_col" not in result
