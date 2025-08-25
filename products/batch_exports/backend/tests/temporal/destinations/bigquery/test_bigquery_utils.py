"""Test module covering utilities used for batch exporting to BigQuery."""

import datetime as dt

import pytest

import pyarrow as pa
from google.cloud import bigquery

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    get_bigquery_fields_from_record_schema,
)


@pytest.mark.parametrize(
    "pyrecords,expected_schema",
    [
        ([{"test": 1}], [bigquery.SchemaField("test", "INT64")]),
        ([{"test": "a string"}], [bigquery.SchemaField("test", "STRING")]),
        ([{"test": b"a bytes"}], [bigquery.SchemaField("test", "BYTES")]),
        ([{"test": 6.0}], [bigquery.SchemaField("test", "FLOAT64")]),
        ([{"test": True}], [bigquery.SchemaField("test", "BOOL")]),
        ([{"test": dt.datetime.now()}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        ([{"test": dt.datetime.now(tz=dt.UTC)}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        (
            [
                {
                    "test_int": 1,
                    "test_str": "a string",
                    "test_bytes": b"a bytes",
                    "test_float": 6.0,
                    "test_bool": False,
                    "test_timestamp": dt.datetime.now(),
                    "test_timestamptz": dt.datetime.now(tz=dt.UTC),
                }
            ],
            [
                bigquery.SchemaField("test_int", "INT64"),
                bigquery.SchemaField("test_str", "STRING"),
                bigquery.SchemaField("test_bytes", "BYTES"),
                bigquery.SchemaField("test_float", "FLOAT64"),
                bigquery.SchemaField("test_bool", "BOOL"),
                bigquery.SchemaField("test_timestamp", "TIMESTAMP"),
                bigquery.SchemaField("test_timestamptz", "TIMESTAMP"),
            ],
        ),
    ],
)
def test_get_bigquery_fields_from_record_schema(pyrecords, expected_schema):
    """Test BigQuery schema fields generated from record match expected."""
    record_batch = pa.RecordBatch.from_pylist(pyrecords)
    schema = get_bigquery_fields_from_record_schema(record_batch.schema, known_json_columns=[])

    assert schema == expected_schema
