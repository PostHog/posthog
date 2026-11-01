import pytest

import pyarrow as pa

from posthog.temporal.common.arrow_pipeline.json_type import (
    JsonType,
    cast_record_batch_json_columns,
    cast_record_batch_schema_json_columns,
)


@pytest.mark.parametrize(
    "input,expected",
    [
        ([b'{"asdf": "\\udee5\\ud83e\\udee5\\ud83e"}'], [{"asdf": "????"}]),
        ([b'{"asdf": "\\"Hello\\" \\udfa2"}'], [{"asdf": '"Hello" ?'}]),
        ([b'{"asdf": "\n"}'], [{"asdf": "\n"}]),
        ([b'{"asdf": "\\n"}'], [{"asdf": "\n"}]),
        (
            [b'{"finally": "a", "normal": "json", "thing": 1, "bool": false}'],
            [{"finally": "a", "normal": "json", "thing": 1, "bool": False}],
        ),
    ],
)
def test_json_type_as_py(input, expected):
    array = pa.array(input)
    casted_array = array.cast(JsonType())
    result = casted_array.to_pylist()

    assert result == expected


@pytest.mark.parametrize(
    "json_columns, expected_json_columns",
    [
        ((), set()),
        (("properties",), {"properties"}),
        (("properties", "set", "missing"), {"properties", "set"}),
    ],
)
def test_cast_record_batch_json_columns(json_columns, expected_json_columns):
    record_batch = pa.RecordBatch.from_pylist([{"event": "a", "properties": '{"a": 1}', "set": '{"b": 2}', "count": 1}])

    casted = cast_record_batch_json_columns(record_batch, json_columns=json_columns)
    casted_schema = cast_record_batch_schema_json_columns(record_batch.schema, json_columns=json_columns)

    assert {field.name for field in casted.schema if field.type == JsonType()} == expected_json_columns
    assert {field.name for field in casted_schema if field.type == JsonType()} == expected_json_columns
    assert casted.to_pylist()[0]["event"] == "a"
