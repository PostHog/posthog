"""The unsigned-to-signed cast in isolation: pure pyarrow, no database, no delta table.

The incremental suite proves the cast is wired into both write paths. These cover the type
mapping itself, where Delta Lake's lack of an unsigned integer reaches values nested in a
list, a struct or a map.
"""

import pytest

import pyarrow as pa

from posthog.temporal.data_modeling.activities.materialize_view import (
    UnstorableIntegerError,
    _transform_unsigned_integers,
)


@pytest.mark.parametrize(
    "column,expected_type",
    [
        pytest.param(pa.array([200], pa.uint8()), pa.int16(), id="uint8_widens_past_its_signed_max"),
        pytest.param(pa.array([60000], pa.uint16()), pa.int32(), id="uint16_widens_past_its_signed_max"),
        pytest.param(pa.array([4000000000], pa.uint32()), pa.int64(), id="uint32_widens_past_its_signed_max"),
        pytest.param(pa.array([5000000000], pa.uint64()), pa.int64(), id="uint64_has_no_wider_signed_type"),
        pytest.param(pa.array([[1, 2]], pa.list_(pa.uint64())), pa.list_(pa.int64()), id="list_value"),
        pytest.param(pa.array([[1, 2]], pa.large_list(pa.uint64())), pa.large_list(pa.int64()), id="large_list_value"),
        pytest.param(
            pa.array([{"a": 250}], pa.struct([pa.field("a", pa.uint8())])),
            pa.struct([pa.field("a", pa.int16())]),
            id="struct_field",
        ),
        pytest.param(
            pa.array([[("k", 7)]], pa.map_(pa.string(), pa.uint32())),
            pa.map_(pa.string(), pa.int64()),
            id="map_value",
        ),
        pytest.param(pa.array(["x"], pa.string()), pa.string(), id="a_type_delta_already_stores_is_untouched"),
    ],
)
def test_unsigned_integers_become_the_type_delta_stores(column: pa.Array, expected_type: pa.DataType) -> None:
    batch = pa.RecordBatch.from_arrays([column], names=["c"])

    transformed = _transform_unsigned_integers(batch)

    assert transformed.schema.field("c").type.equals(expected_type)
    assert transformed.column("c").to_pylist() == column.to_pylist()


@pytest.mark.parametrize(
    "column",
    [
        pytest.param(pa.array([2**64 - 1], pa.uint64()), id="scalar"),
        pytest.param(pa.array([[2**64 - 1]], pa.list_(pa.uint64())), id="nested_in_a_list"),
    ],
)
def test_a_uint64_above_the_signed_maximum_names_its_column(column: pa.Array) -> None:
    batch = pa.RecordBatch.from_arrays([column], names=["hash_id"])

    with pytest.raises(UnstorableIntegerError) as raised:
        _transform_unsigned_integers(batch)

    assert raised.value.column == "hash_id"
