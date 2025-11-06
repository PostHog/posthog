import io
import csv
import json
import typing
import datetime as dt
import functools

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.pipeline.table import (
    Field,
    Table,
    TypeTupleToCastMapping,
    _make_ensure_array,
)
from products.batch_exports.backend.temporal.pipeline.transformer import (
    CSVStreamTransformer,
    JSONLStreamTransformer,
    PipelineTransformer,
    SchemaTransformer,
    dump_dict,
)
from products.batch_exports.backend.temporal.utils import JsonType


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
        max_file_size_bytes=0,
    )

    record_batch = record_batch.sort_by("_inserted_at")

    async def record_batches():
        yield record_batch

    chunks = []
    async for chunk in transformer.iter(record_batches()):
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


class TestField(Field):
    def __init__(self, name: str, data_type: pa.DataType):
        self.name = name
        self.data_type = data_type

    @classmethod
    def from_arrow_field(cls, field: pa.Field) -> typing.Self:
        raise NotImplementedError()

    def to_arrow_field(cls) -> pa.Field:
        raise NotImplementedError()

    @classmethod
    def from_destination_field(cls, field: typing.Any) -> typing.Self:
        raise NotImplementedError()

    def to_destination_field(cls) -> typing.Any:
        raise NotImplementedError()

    def with_new_arrow_type(self, new_type: pa.DataType) -> "TestField":
        raise NotImplementedError()


async def test_transformer_pipeline_pipes_multiple_transformers():
    """Test piping a `SchemaTransformer` into a `JSONLStreamTransformer`."""
    fibo = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    numbers = pa.array(fibo)
    record_batch = pa.RecordBatch.from_arrays([numbers], names=("number",))

    async def record_batch_iter():
        yield record_batch
        return

    class TestTable(Table):
        @classmethod
        def from_arrow_schema(cls, schema: pa.Schema, **kwargs) -> typing.Self:
            return cls(name="test", fields=[TestField("number", pa.string())])

    t = TestTable.from_arrow_schema(record_batch.schema)
    pipeline = PipelineTransformer(
        (
            SchemaTransformer(
                t,
                {
                    (pa.int64(), pa.string()): _make_ensure_array(
                        functools.partial(pa.compute.cast, target_type=pa.string())
                    )
                },
            ),
            JSONLStreamTransformer(),
        )
    )

    transformed_jsonl_bytes = [chunk.data async for chunk in pipeline.iter(record_batch_iter())]

    seen = []
    for expected_number, transformed_jsonl in zip(fibo, b"".join(transformed_jsonl_bytes).decode("utf-8").split("\n")):
        doc = json.loads(transformed_jsonl)

        assert "number" in doc
        assert doc["number"] == str(expected_number)
        seen.append(expected_number)

    # Make sure all the numbers went through the transformer, as zip stops on the
    # shortest iterator in case they are not the same length.
    assert fibo == seen


FIBO = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
NUMBERS = pa.array(FIBO)
NUMBERS_RECORD_BATCH = pa.RecordBatch.from_arrays([NUMBERS], names=["number"])

EPOCH = dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
DATES = [dt.datetime(2025, 1, 1, 1, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 2, 1, 1, 1, tzinfo=dt.UTC)]
DATES_SECONDS_RECORD_BATCH = pa.RecordBatch.from_arrays(
    [pa.array(DATES, type=pa.timestamp("s", tz="UTC"))], names=["date"]
)
DATES_MILLISECONDS_RECORD_BATCH = pa.RecordBatch.from_arrays(
    [pa.array(DATES, type=pa.timestamp("ms", tz="UTC"))], names=["date"]
)
DATES_MICROSECONDS_RECORD_BATCH = pa.RecordBatch.from_arrays(
    [pa.array(DATES, type=pa.timestamp("us", tz="UTC"))], names=["date"]
)


@pytest.mark.parametrize(
    "target_type,record_batch,compatible_types,expected_pylist",
    (
        # int64 -> string
        (
            pa.string(),
            NUMBERS_RECORD_BATCH,
            {
                (pa.int64(), pa.string()): _make_ensure_array(
                    functools.partial(pa.compute.cast, target_type=pa.string())
                )
            },
            [{"number": str(n)} for n in FIBO],
        ),
        # int64 -> int64, no change required
        (
            pa.int64(),
            NUMBERS_RECORD_BATCH,
            {},
            [{"number": n} for n in FIBO],
        ),
        # string -> JsonType
        (
            JsonType(),
            pa.RecordBatch.from_arrays([pa.array(['{"one": 1}', '{"two": 2}'], type=pa.string())], names=["json"]),
            {},
            [{"json": {"one": 1}}, {"json": {"two": 2}}],
        ),
        # timestamp("s", "UTC") -> int64
        (
            pa.int64(),
            DATES_SECONDS_RECORD_BATCH,
            {},
            [{"date": d.timestamp()} for d in DATES],
        ),
        # timestamp("ms", "UTC") -> int64
        (
            pa.int64(),
            DATES_MILLISECONDS_RECORD_BATCH,
            {
                (pa.timestamp("ms", tz="UTC"), pa.int64()): _make_ensure_array(
                    functools.partial(
                        pa.compute.milliseconds_between, pa.scalar(EPOCH, type=pa.timestamp("ms", tz="UTC"))
                    )
                )
            },
            [{"date": d.timestamp() * 1_000} for d in DATES],
        ),
        # timestamp("us", "UTC") -> int64
        (
            pa.int64(),
            DATES_MICROSECONDS_RECORD_BATCH,
            {
                (pa.timestamp("us", tz="UTC"), pa.int64()): _make_ensure_array(
                    functools.partial(
                        pa.compute.microseconds_between, pa.scalar(EPOCH, type=pa.timestamp("us", tz="UTC"))
                    )
                )
            },
            [{"date": d.timestamp() * 1_000_000} for d in DATES],
        ),
    ),
)
async def test_schema_transformer(
    target_type: pa.DataType,
    record_batch: pa.RecordBatch,
    compatible_types: TypeTupleToCastMapping,
    expected_pylist: list[dict[str, typing.Any]],
):
    """Test `SchemaTransformer` produces record batches with the right types."""

    async def record_batch_iter():
        yield record_batch
        return

    class TestTable(Table):
        @classmethod
        def from_arrow_schema(cls, schema: pa.Schema, **kwargs) -> typing.Self:
            return cls(name="test", fields=[TestField(record_batch[0]._name, target_type)])  # type: ignore[attr-defined]

    t = TestTable.from_arrow_schema(record_batch.schema)
    transformer = SchemaTransformer(t, compatible_types)

    transformed_record_batches = [record_batch async for record_batch in transformer.iter(record_batch_iter())]

    assert len(transformed_record_batches) == 1
    assert transformed_record_batches[0][record_batch[0]._name].type == target_type  # type: ignore[attr-defined]
    assert transformed_record_batches[0].to_pylist() == expected_pylist
