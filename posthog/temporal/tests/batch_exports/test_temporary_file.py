import csv
import io
import json

import pytest

from posthog.temporal.batch_exports.temporary_file import (
    BatchExportTemporaryFile,
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

        rows = [row for row in reader]
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

        rows = [row for row in reader]
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
