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
