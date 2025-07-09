import csv
import datetime as dt
import io
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from products.batch_exports.backend.temporal.temporary_file import (
    BatchExportTemporaryFile,
    CSVBatchExportWriter,
    DateRange,
    JSONLBatchExportWriter,
    ParquetBatchExportWriter,
    json_dumps_bytes,
)


@pytest.mark.parametrize(
    "to_write",
    [
        (b"",),
        (b"", b""),
        (b"12345",),
        (b"12345", b"12345"),
        (b"abbcccddddeeeee",),
        (b"abbcccddddeeeee", b"abbcccddddeeeee"),
    ],
)
def test_batch_export_temporary_file_tracks_bytes(to_write):
    """Test the bytes written by BatchExportTemporaryFile match expected."""
    with BatchExportTemporaryFile() as be_file:
        for content in to_write:
            be_file.write(content)

        assert be_file.bytes_total == sum(len(content) for content in to_write)
        assert be_file.bytes_since_last_reset == sum(len(content) for content in to_write)

        be_file.reset()

        assert be_file.bytes_total == sum(len(content) for content in to_write)
        assert be_file.bytes_since_last_reset == 0


TEST_RECORDS = [
    [],
    [
        {"id": "record-1", "property": "value", "property_int": 1},
        {"id": "record-2", "property": "another-value", "property_int": 2},
        {
            "id": "record-3",
            "property": {"id": "nested-record", "property": "nested-value"},
            "property_int": 3,
        },
    ],
]


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_jsonl(records):
    """Test JSONL records written by BatchExportTemporaryFile match expected."""
    jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

    with BatchExportTemporaryFile() as be_file:
        be_file.write_records_to_jsonl(records)

        assert be_file.bytes_total == len(jsonl_dump)
        assert be_file.bytes_since_last_reset == len(jsonl_dump)
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        lines = be_file.readlines()
        assert len(lines) == len(records)

        for line_index, jsonl_record in enumerate(lines):
            json_loaded = json.loads(jsonl_record)
            assert json_loaded == records[line_index]

        be_file.reset()

        assert be_file.bytes_total == len(jsonl_dump)
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


def test_batch_export_temporary_file_write_records_to_jsonl_invalid_unicode():
    with BatchExportTemporaryFile() as be_file:
        be_file.write_records_to_jsonl(["hello\ud83dworld"])

        be_file.seek(0)
        # Invalid single surrogate is replaced with a question mark.
        assert json.loads(be_file.readlines()[0]) == "hello?world"


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_csv(records):
    """Test CSV written by BatchExportTemporaryFile match expected."""
    in_memory_file_obj = io.StringIO()
    writer = csv.DictWriter(
        in_memory_file_obj,
        fieldnames=records[0].keys() if len(records) > 0 else [],
        delimiter=",",
        quotechar='"',
        escapechar="\\",
        lineterminator="\n",
        quoting=csv.QUOTE_NONE,
    )
    writer.writerows(records)

    with BatchExportTemporaryFile(mode="w+") as be_file:
        be_file.write_records_to_csv(records)

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == in_memory_file_obj.tell()
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        reader = csv.reader(
            be_file._file,
            delimiter=",",
            quotechar='"',
            escapechar="\\",
            quoting=csv.QUOTE_NONE,
        )

        rows = list(reader)
        assert len(rows) == len(records)

        for row_index, csv_record in enumerate(rows):
            for value_index, value in enumerate(records[row_index].values()):
                # Everything returned by csv.reader is a str.
                # This means type information is lost when writing to CSV
                # but this just a limitation of the format.
                assert csv_record[value_index] == str(value)

        be_file.reset()

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_tsv(records):
    """Test TSV written by BatchExportTemporaryFile match expected."""
    in_memory_file_obj = io.StringIO()
    writer = csv.DictWriter(
        in_memory_file_obj,
        fieldnames=records[0].keys() if len(records) > 0 else [],
        delimiter="\t",
        quotechar='"',
        escapechar="\\",
        lineterminator="\n",
        quoting=csv.QUOTE_NONE,
    )
    writer.writerows(records)

    with BatchExportTemporaryFile(mode="w+") as be_file:
        be_file.write_records_to_tsv(records)

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == in_memory_file_obj.tell()
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        reader = csv.reader(
            be_file._file,
            delimiter="\t",
            quotechar='"',
            escapechar="\\",
            quoting=csv.QUOTE_NONE,
        )

        rows = list(reader)
        assert len(rows) == len(records)

        for row_index, csv_record in enumerate(rows):
            for value_index, value in enumerate(records[row_index].values()):
                # Everything returned by csv.reader is a str.
                # This means type information is lost when writing to CSV
                # but this just a limitation of the format.
                assert csv_record[value_index] == str(value)

        be_file.reset()

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


TEST_RECORD_BATCHES = [
    pa.RecordBatch.from_pydict(
        {
            "event": pa.array(["test-event-0", "test-event-1", "test-event-2"]),
            "properties": pa.array(['{"prop_0": 1, "prop_1": 2}', "{}", "null"]),
            "_inserted_at": pa.array(
                [dt.datetime.fromtimestamp(0), dt.datetime.fromtimestamp(1), dt.datetime.fromtimestamp(2)]
            ),
        }
    )
]


@pytest.mark.parametrize(
    "record_batch",
    TEST_RECORD_BATCHES,
)
@pytest.mark.asyncio
async def test_jsonl_writer_writes_record_batches(record_batch):
    """Test record batches are written as valid JSONL."""
    in_memory_file_obj = io.BytesIO()
    date_ranges_seen: list[DateRange] = []

    async def store_in_memory_on_flush(
        batch_export_file,
        records_since_last_flush,
        bytes_since_last_flush,
        flush_counter,
        last_date_range,
        is_last,
        error,
    ):
        assert writer.records_since_last_flush == record_batch.num_rows
        in_memory_file_obj.write(batch_export_file.read())
        date_ranges_seen.append(last_date_range)

    writer = JSONLBatchExportWriter(max_bytes=1, flush_callable=store_in_memory_on_flush)

    record_batch = record_batch.sort_by("_inserted_at")
    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

    assert writer.records_total == record_batch.num_rows

    in_memory_file_obj.seek(0)
    lines = in_memory_file_obj.readlines()
    for index, line in enumerate(lines):
        written_jsonl = json.loads(line)

        single_record_batch = record_batch.slice(offset=index, length=1)
        expected_jsonl = single_record_batch.to_pylist()[0]

        assert "_inserted_at" not in written_jsonl
        assert written_jsonl == {k: v for k, v in expected_jsonl.items() if k != "_inserted_at"}

    assert date_ranges_seen == [
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py())
    ]


@pytest.mark.parametrize(
    "record_batch",
    TEST_RECORD_BATCHES,
)
@pytest.mark.asyncio
async def test_csv_writer_writes_record_batches(record_batch):
    """Test record batches are written as valid CSV."""
    in_memory_file_obj = io.StringIO()
    date_ranges_seen: list[DateRange] = []

    async def store_in_memory_on_flush(
        batch_export_file,
        records_since_last_flush,
        bytes_since_last_flush,
        flush_counter,
        last_date_range,
        is_last,
        error,
    ):
        in_memory_file_obj.write(batch_export_file.read().decode("utf-8"))
        date_ranges_seen.append(last_date_range)

    schema_columns = [column_name for column_name in record_batch.column_names if column_name != "_inserted_at"]
    writer = CSVBatchExportWriter(max_bytes=1, field_names=schema_columns, flush_callable=store_in_memory_on_flush)

    record_batch = record_batch.sort_by("_inserted_at")
    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

    in_memory_file_obj.seek(0)
    reader = csv.reader(
        in_memory_file_obj,
        delimiter=",",
        quotechar='"',
        escapechar="\\",
        quoting=csv.QUOTE_NONE,
    )
    for index, written_csv_row in enumerate(reader):
        single_record_batch = record_batch.slice(offset=index, length=1)
        expected_dict = single_record_batch.to_pylist()[0]

        assert "_inserted_at" not in written_csv_row
        assert written_csv_row == list({k: v for k, v in expected_dict.items() if k != "_inserted_at"}.values())

    assert date_ranges_seen == [
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py())
    ]


@pytest.mark.parametrize(
    "record_batch",
    TEST_RECORD_BATCHES,
)
@pytest.mark.asyncio
async def test_parquet_writer_writes_record_batches(record_batch):
    """Test record batches are written as valid Parquet."""
    in_memory_file_obj = io.BytesIO()
    date_ranges_seen: list[DateRange] = []

    async def store_in_memory_on_flush(
        batch_export_file,
        records_since_last_flush,
        bytes_since_last_flush,
        flush_counter,
        last_date_range,
        is_last,
        error,
    ):
        in_memory_file_obj.write(batch_export_file.read())
        date_ranges_seen.append(last_date_range)

    schema_columns = [column_name for column_name in record_batch.column_names if column_name != "_inserted_at"]

    writer = ParquetBatchExportWriter(
        max_bytes=1,
        flush_callable=store_in_memory_on_flush,
        schema=record_batch.select(schema_columns).schema,
    )

    record_batch = record_batch.sort_by("_inserted_at")
    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

    in_memory_file_obj.seek(0)
    written_parquet = pq.read_table(in_memory_file_obj)

    for index, written_row_as_dict in enumerate(written_parquet.to_pylist()):
        single_record_batch = record_batch.slice(offset=index, length=1)
        expected_row_as_dict = single_record_batch.select(schema_columns).to_pylist()[0]

        assert "_inserted_at" not in written_row_as_dict
        assert written_row_as_dict == expected_row_as_dict

    # NOTE: Parquet gets flushed twice due to the extra flush at the end for footer bytes, so our mock function
    # will see this value twice.
    assert date_ranges_seen == [
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py()),
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py()),
    ]


@pytest.mark.parametrize(
    "record_batch",
    TEST_RECORD_BATCHES,
)
@pytest.mark.asyncio
async def test_writing_out_of_scope_of_temporary_file_raises(record_batch):
    """Test attempting a write out of temporary file scope raises a `ValueError`."""

    async def do_nothing(*args, **kwargs):
        pass

    schema_columns = [column_name for column_name in record_batch.column_names if column_name != "_inserted_at"]
    writer = ParquetBatchExportWriter(
        max_bytes=10,
        flush_callable=do_nothing,
        schema=record_batch.select(schema_columns).schema,
    )

    async with writer.open_temporary_file():
        pass

    with pytest.raises(ValueError, match="Batch export file is closed"):
        await writer.write_record_batch(record_batch)


@pytest.mark.parametrize(
    "record_batch",
    TEST_RECORD_BATCHES,
)
@pytest.mark.asyncio
async def test_flushing_parquet_writer_resets_underlying_file(record_batch):
    """Test flushing a writer resets underlying file."""
    flush_counter = 0

    async def track_flushes(*args, **kwargs):
        nonlocal flush_counter
        flush_counter += 1

    schema_columns = [column_name for column_name in record_batch.column_names if column_name != "_inserted_at"]
    writer = ParquetBatchExportWriter(
        max_bytes=10000000,
        flush_callable=track_flushes,
        schema=record_batch.select(schema_columns).schema,
    )

    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

        assert writer.batch_export_file.tell() > 0
        assert writer.bytes_since_last_flush > 0
        assert writer.bytes_since_last_flush == writer.batch_export_file.bytes_since_last_reset
        assert writer.records_since_last_flush == record_batch.num_rows

        await writer.flush()

        assert flush_counter == 1
        assert writer.batch_export_file.tell() == 0
        assert writer.bytes_since_last_flush == 0
        assert writer.bytes_since_last_flush == writer.batch_export_file.bytes_since_last_reset
        assert writer.records_since_last_flush == 0

    assert flush_counter == 2


@pytest.mark.asyncio
async def test_jsonl_writer_deals_with_web_vitals():
    """Test old $web_vitals record batches are written as valid JSONL."""
    in_memory_file_obj = io.BytesIO()
    date_ranges_seen: list[DateRange] = []

    record_batch = pa.RecordBatch.from_pydict(
        {
            "event": pa.array(["$web_vitals"]),
            "properties": pa.array(
                [
                    {
                        "$web_vitals_INP_event": {
                            "attribution": {"interactionTargetElement": json.loads("[" * 256 + "]" * 256)},
                            "somethingElse": 1,
                        }
                    }
                ]
            ),
            "_inserted_at": pa.array([dt.datetime.fromtimestamp(0)]),
        }
    )

    async def store_in_memory_on_flush(
        batch_export_file,
        records_since_last_flush,
        bytes_since_last_flush,
        flush_counter,
        last_date_range,
        is_last,
        error,
    ):
        assert writer.records_since_last_flush == record_batch.num_rows
        in_memory_file_obj.write(batch_export_file.read())
        date_ranges_seen.append(last_date_range)

    writer = JSONLBatchExportWriter(max_bytes=1, flush_callable=store_in_memory_on_flush)

    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

    assert writer.records_total == record_batch.num_rows == 1

    in_memory_file_obj.seek(0)
    lines = in_memory_file_obj.readlines()
    line = lines[0]
    written_jsonl = json.loads(line)
    expected_jsonl = record_batch.to_pylist()[0]

    assert "_inserted_at" not in written_jsonl
    assert "interactionTargetElement" not in written_jsonl["properties"]["$web_vitals_INP_event"]["attribution"]
    assert "interactionTargetElement" in expected_jsonl["properties"]["$web_vitals_INP_event"]["attribution"]

    del expected_jsonl["properties"]["$web_vitals_INP_event"]["attribution"]["interactionTargetElement"]

    assert written_jsonl == {k: v for k, v in expected_jsonl.items() if k != "_inserted_at"}
    assert date_ranges_seen == [
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py())
    ]


@pytest.mark.asyncio
async def test_jsonl_writer_deals_with_nested_user_events():
    """Test very nested user event record batches are written as valid JSONL."""
    in_memory_file_obj = io.BytesIO()
    date_ranges_seen: list[DateRange] = []

    record_batch = pa.RecordBatch.from_pydict(
        {
            "event": pa.array(["my_event"]),
            "properties": pa.array([{"we_have_to_go_deeper": json.loads("[" * 256 + "]" * 256)}]),
            "_inserted_at": pa.array([dt.datetime.fromtimestamp(0)]),
        }
    )

    async def store_in_memory_on_flush(
        batch_export_file,
        records_since_last_flush,
        bytes_since_last_flush,
        flush_counter,
        last_date_range,
        is_last,
        error,
    ):
        assert writer.records_since_last_flush == record_batch.num_rows
        in_memory_file_obj.write(batch_export_file.read())
        date_ranges_seen.append(last_date_range)

    writer = JSONLBatchExportWriter(max_bytes=1, flush_callable=store_in_memory_on_flush)

    record_batch = record_batch.sort_by("_inserted_at")
    async with writer.open_temporary_file():
        await writer.write_record_batch(record_batch)

    assert writer.records_total == record_batch.num_rows

    in_memory_file_obj.seek(0)
    lines = in_memory_file_obj.readlines()
    line = lines[0]
    written_jsonl = json.loads(line)
    expected_jsonl = record_batch.to_pylist()[0]

    assert "_inserted_at" not in written_jsonl
    assert written_jsonl == {k: v for k, v in expected_jsonl.items() if k != "_inserted_at"}
    assert date_ranges_seen == [
        (record_batch.column("_inserted_at")[0].as_py(), record_batch.column("_inserted_at")[-1].as_py())
    ]
