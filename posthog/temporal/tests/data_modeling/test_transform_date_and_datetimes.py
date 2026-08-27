import datetime as dt

import pytest

import pyarrow as pa

from posthog.temporal.data_modeling.activities.materialize_view import _transform_date_and_datetimes as transform_v2
from posthog.temporal.data_modeling.run_workflow import _transform_date_and_datetimes as transform_v1

# v1 (run_workflow.py) is frozen but carries the same code, so both must pass.
TRANSFORMS = [transform_v1, transform_v2]


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_tuple_with_datetime_element_is_left_untouched(transform):
    # ClickHouse returns a Tuple as an Arrow struct, and its DateTime element already
    # arrives as a timestamp. The substring match on the type string used to send the
    # whole struct into the scalar cast, which raised ArrowNotImplementedError.
    tuple_type = pa.struct(
        [
            pa.field("label", pa.string()),
            pa.field("ts", pa.timestamp("us", tz="UTC")),
        ]
    )
    column = pa.array([{"label": "x", "ts": dt.datetime(2022, 1, 1, 12, 0, tzinfo=dt.UTC)}], type=tuple_type)
    batch = pa.RecordBatch.from_arrays([column], names=["payload"])

    result = transform(batch, [("payload", "Tuple(String, DateTime64(6, 'UTC'))")])

    assert result.schema.field("payload").type == tuple_type
    assert result.column("payload").to_pylist() == column.to_pylist()


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_nested_datetime_column_is_left_untouched(transform):
    # A ClickHouse Nested column arrives as list<struct>. The list branch must not try to
    # cast its struct elements to integers.
    element_type = pa.struct([pa.field("ts", pa.timestamp("us", tz="UTC"))])
    list_type = pa.list_(element_type)
    column = pa.array([[{"ts": dt.datetime(2022, 1, 1, tzinfo=dt.UTC)}]], type=list_type)
    batch = pa.RecordBatch.from_arrays([column], names=["events"])

    result = transform(batch, [("events", "Array(Tuple(DateTime64(6, 'UTC')))")])

    assert result.schema.field("events").type == list_type
    assert result.column("events").to_pylist() == column.to_pylist()


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_scalar_datetime_is_still_converted(transform):
    # Guard that the struct skip does not stop a plain DateTime column from converting
    # from the ClickHouse UInt32 (seconds) representation back to a timestamp.
    column = pa.array([1640995200], type=pa.uint32())  # 2022-01-01T00:00:00Z
    batch = pa.RecordBatch.from_arrays([column], names=["ts"])

    result = transform(batch, [("ts", "DateTime")])

    assert pa.types.is_timestamp(result.schema.field("ts").type)
    assert result.column("ts")[0].as_py() == dt.datetime(2022, 1, 1, tzinfo=dt.UTC)
