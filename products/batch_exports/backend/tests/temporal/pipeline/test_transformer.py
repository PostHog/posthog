import io
import csv
import json
import typing
import datetime as dt

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer, dump_dict


def create_deeply_nested_dict(depth: int, value: str = "test") -> typing.Any:
    """Create a dict with specified nesting depth."""
    result = value
    for _ in range(depth):
        result = {"nested": result}
    return result


@pytest.mark.parametrize(
    "input_dict, expected_output",
    [
        # orjson doesn't support integers exceeding 64-bit range, so ensure we fall back to json.dumps correctly
        ({"large_integer": 12345678901234567890987654321}, b'{"large_integer": 12345678901234567890987654321}\n'),
        # Complex nested case with datetime and various types
        (
            {
                "timestamp": "2023-01-01T12:00:00Z",
                "nested": {
                    "array": [1, 2, 3],
                    "big_num": 12345678901234567890987654321,
                    "null_value": None,
                    "bool_value": True,
                    "unicode": "Hello 👋 世界",
                },
                "list_of_objects": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}],
            },
            b'{"timestamp": "2023-01-01T12:00:00Z", "nested": {"array": [1, 2, 3], "big_num": 12345678901234567890987654321, "null_value": null, "bool_value": true, "unicode": "Hello \\ud83d\\udc4b \\u4e16\\u754c"}, "list_of_objects": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}]}\n',
        ),
    ],
)
def test_dump_dict(input_dict, expected_output):
    """Test json_dumps_bytes handles integers exceeding 64-bit range."""
    result = dump_dict(input_dict)
    assert result == expected_output
    assert isinstance(result, bytes)
    # check the reverse direction
    assert json.loads(result) == input_dict


def test_dump_dict_with_deeply_nested_dict():
    """Test dump_dict with a deeply nested dict."""
    deeply_nested_dict = create_deeply_nested_dict(300)
    result = dump_dict(deeply_nested_dict)
    assert result == json.dumps(deeply_nested_dict, default=str).encode("utf-8") + b"\n"
    assert isinstance(result, bytes)
    # check the reverse direction
    assert json.loads(result) == deeply_nested_dict


TEST_RECORDS = [
    {
        "event": "test-event-0",
        "properties": '{"prop_0": 1, "prop_1": 2}',
        "timestamp": dt.datetime.fromtimestamp(0),
        "_inserted_at": dt.datetime.fromtimestamp(0),
    },
    {
        "event": "test-event-1",
        "properties": "{}",
        "timestamp": dt.datetime.fromtimestamp(1),
        "_inserted_at": dt.datetime.fromtimestamp(1),
    },
    {
        "event": "test-event-2",
        "properties": "null",
        "timestamp": dt.datetime.fromtimestamp(2),
        "_inserted_at": dt.datetime.fromtimestamp(2),
    },
]


@pytest.mark.asyncio
async def test_csv_stream_transformer_writes_record_batches():
    """Test record batches are written as valid CSV by CSVStreamTransformer."""
    record_batch = pa.RecordBatch.from_pylist(TEST_RECORDS)
    schema_columns = [column_name for column_name in record_batch.column_names if column_name != "_inserted_at"]

    transformer = CSVStreamTransformer(
        field_names=schema_columns,
        delimiter=",",
        quote_char='"',
        escape_char="\\",
        quoting=csv.QUOTE_NONE,
        include_inserted_at=False,
    )

    record_batch = record_batch.sort_by("_inserted_at")

    async def record_batches():
        yield record_batch

    chunks = []
    async for chunk in transformer.iter(record_batches(), max_file_size_bytes=0):
        if chunk.data:
            chunks.append(chunk.data)

    csv_data = b"".join(chunks).decode("utf-8")

    # Assert number of rows matches the record batch (count newlines)
    num_rows = csv_data.count("\n")
    assert num_rows == record_batch.num_rows

    # verify we can read the CSV back using a csv.reader
    csv_reader = csv.reader(
        io.StringIO(csv_data),
        delimiter=",",
        quotechar='"',
        escapechar="\\",
        quoting=csv.QUOTE_NONE,
    )
    read_rows = list(csv_reader)

    # Verify we can read back the correct number of rows
    assert len(read_rows) == record_batch.num_rows

    # Verify each row has the correct values
    for index, row in enumerate(read_rows):
        assert "_inserted_at" not in row
        expected_row = [str(v) for k, v in TEST_RECORDS[index].items() if k != "_inserted_at"]
        assert row == expected_row
