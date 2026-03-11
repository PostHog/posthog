import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema


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

    def test_json_type_not_downgraded_on_subsequent_add(self):
        schema = HogQLSchema()

        # First batch: JSON detected
        table1 = pa.table({"col": pa.array(['{"key": "value"}'], type=pa.string())})
        schema.add_pyarrow_table(table1)
        assert schema.schema["col"] == "StringJSONDatabaseField"

        # Second batch: first value is plain string — should NOT downgrade
        table2 = pa.table({"col": pa.array(["plain text"], type=pa.string())})
        schema.add_pyarrow_table(table2)
        assert schema.schema["col"] == "StringJSONDatabaseField"
