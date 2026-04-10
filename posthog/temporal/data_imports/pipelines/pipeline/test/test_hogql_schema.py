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
