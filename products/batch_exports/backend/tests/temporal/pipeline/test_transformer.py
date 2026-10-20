import io
import csv
import json
import random
import typing
import hashlib
import datetime as dt
import functools
import collections.abc

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

from products.batch_exports.backend.temporal.pipeline.table import (
    Field,
    Table,
    TypeTupleToCastMapping,
    _make_ensure_array,
)
from products.batch_exports.backend.temporal.pipeline.transformer import (
    CSVStreamTransformer,
    JSONLStreamTransformer,
    ParquetStreamTransformer,
    PipelineTransformer,
    SchemaTransformer,
    _ensure_curly_brackets_array,
    dump_dict,
)
from products.batch_exports.backend.temporal.utils import JsonType


def create_deeply_nested_dict(depth: int, value: str = "test") -> typing.Any:
    """Create a dict with specified nesting depth."""
    result: typing.Any = value
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


async def iterate_record_batches(
    record_batches: list[pa.RecordBatch],
) -> collections.abc.AsyncIterator[pa.RecordBatch]:
    for record_batch in record_batches:
        yield record_batch


async def collect_parquet_files(
    transformer: ParquetStreamTransformer, record_batches: list[pa.RecordBatch]
) -> list[bytes]:
    files: list[bytes] = []
    current_file = b""
    async for chunk in transformer.iter(iterate_record_batches(record_batches)):
        current_file += chunk.data
        if chunk.is_eof:
            files.append(current_file)
            current_file = b""
    return files


@pytest.mark.parametrize(
    "max_file_size_bytes,compression",
    [(0, None), (256 * 1024, None), (256 * 1024, "zstd")],
)
@pytest.mark.asyncio
async def test_parquet_stream_transformer_writes_small_record_batches_as_large_row_groups(
    max_file_size_bytes, compression
):
    records = [
        {
            "uuid": f"uuid-{index}",
            "properties": json.dumps(
                {
                    "index": index,
                    "padding": "".join(hashlib.sha256(f"{index}-{n}".encode()).hexdigest() for n in range(16)),
                }
            ),
        }
        for index in range(1000)
    ]
    record_batches = pa.Table.from_pylist(records).to_batches(max_chunksize=10)

    transformer = ParquetStreamTransformer(
        compression=compression, max_file_size_bytes=max_file_size_bytes, max_buffered_arrow_bytes=64 * 1024
    )
    files = await collect_parquet_files(transformer, record_batches)

    parquet_files = [pq.ParquetFile(io.BytesIO(file)) for file in files]
    assert all(parquet_file.metadata.num_rows > 0 for parquet_file in parquet_files)
    # Writing each record batch as its own row group would give one row group per batch. The exact count
    # depends on where files split and on the learned compression ratio, so only check that batches are combined.
    assert sum(parquet_file.metadata.num_row_groups for parquet_file in parquet_files) < len(record_batches) / 2
    assert [row for parquet_file in parquet_files for row in parquet_file.read().to_pylist()] == records
    # A file closes when less than 5% of its max size is left, and can go over by the error in the compression
    # ratio, so full files land near the max but not on it. The last file holds the remaining rows, so it can be small.
    if max_file_size_bytes:
        assert len(files) > 1
        assert all(0.9 * max_file_size_bytes <= len(file) <= 1.1 * max_file_size_bytes for file in files[:-1])


@pytest.mark.asyncio
async def test_parquet_stream_transformer_bounds_file_size_when_compression_gets_worse():
    max_file_size_bytes = 1024 * 1024
    rng = random.Random(0)
    compressible = [
        pa.RecordBatch.from_pydict({"properties": ['{"a": "' + "x" * 10_000 + '"}'] * 20}) for _ in range(30)
    ]
    incompressible = [
        pa.RecordBatch.from_pydict({"properties": [rng.randbytes(5_000).hex() for _ in range(20)]}) for _ in range(40)
    ]

    transformer = ParquetStreamTransformer(compression="zstd", max_file_size_bytes=max_file_size_bytes)
    files = await collect_parquet_files(transformer, compressible + incompressible)

    assert max(len(file) for file in files) <= 2 * max_file_size_bytes


@pytest.mark.asyncio
async def test_parquet_stream_transformer_skips_statistics_and_dictionaries_only_for_json_columns():
    record_batch = pa.RecordBatch.from_pylist(
        [
            {"uuid": "a", "tags": ["x", "y"], "person": {"name": "a"}, "properties": '{"a": 1}'},
            {"uuid": "b", "tags": ["z"], "person": {"name": "b"}, "properties": '{"b": 2}'},
        ]
    )

    transformer = ParquetStreamTransformer()
    (data,) = await collect_parquet_files(transformer, [record_batch])

    row_group = pq.ParquetFile(io.BytesIO(data)).metadata.row_group(0)
    columns = [row_group.column(index) for index in range(row_group.num_columns)]
    assert {
        column.path_in_schema: column.statistics is not None and column.statistics.has_min_max for column in columns
    } == {
        "uuid": True,
        "tags.list.element": True,
        "person.name": True,
        "properties": False,
    }
    assert {column.path_in_schema: "RLE_DICTIONARY" in column.encodings for column in columns} == {
        "uuid": True,
        "tags.list.element": True,
        "person.name": True,
        "properties": False,
    }


@pytest.mark.asyncio
async def test_parquet_stream_transformer_without_metrics_runs_outside_temporal(settings):
    # get_metric_meter only raises outside Temporal when DEBUG and TEST are both off.
    settings.DEBUG = False
    settings.TEST = False

    transformer = ParquetStreamTransformer(record_metrics=False, max_buffered_arrow_bytes=1)
    (data,) = await collect_parquet_files(transformer, [pa.RecordBatch.from_pylist([{"uuid": "a"}])])

    assert pq.ParquetFile(io.BytesIO(data)).metadata.num_rows == 1


class FakeField(Field):
    def __init__(self, name: str, data_type: pa.DataType):
        self.name = name
        self.alias = name
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

    def with_new_arrow_type(self, new_type: pa.DataType) -> "FakeField":
        raise NotImplementedError()


async def test_transformer_pipeline_pipes_multiple_transformers():
    """Test piping a `SchemaTransformer` into a `JSONLStreamTransformer`."""
    fibo = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    numbers = pa.array(fibo)
    record_batch = pa.RecordBatch.from_arrays(
        [numbers],
        names=[
            "number",
        ],
    )

    async def record_batch_iter():
        yield record_batch
        return

    class TestTable(Table):
        pass

    t = TestTable(name="test", fields=[FakeField("number", pa.string())])
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
        pass

    t = TestTable(name="test", fields=[FakeField(record_batch[0]._name, target_type), FakeField("extra", pa.string())])  # type: ignore[attr-defined]
    transformer = SchemaTransformer(t, compatible_types)

    transformed_record_batches = [record_batch async for record_batch in transformer.iter(record_batch_iter())]

    assert len(transformed_record_batches) == 1
    assert transformed_record_batches[0][record_batch[0]._name].type == target_type  # type: ignore[attr-defined]
    assert transformed_record_batches[0].to_pylist() == expected_pylist


@pytest.mark.parametrize(
    "input_list,expected_output",
    [
        ([1, 2, 3], "{1,2,3}"),
        (["a", "b", "c"], "{a,b,c}"),
        ([], "{}"),
        # Nested arrays
        ([[1, 2], [3, 4]], "{{1,2},{3,4}}"),
        ([["a", "b"], ["c", "d"]], "{{a,b},{c,d}}"),
        # String contains `{}`
        (["has {braces}"], '{"has {braces}"}'),
    ],
)
def test_ensure_curly_brackets_array(input_list, expected_output):
    """Test ensure_curly_brackets_array converts Python lists to PostgreSQL array format."""
    result = _ensure_curly_brackets_array(input_list)
    assert result == expected_output
