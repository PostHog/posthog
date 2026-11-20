"""The Arrow transforms ahead of the Delta write, in isolation: pyarrow and a local Delta table,
no database.

The incremental suite proves the transforms are wired into both write paths. These cover the
type mappings themselves, where Delta Lake's lack of unsigned integers and of decimals wider
than 128 bits reaches values nested in a list, a struct or a map, and where Delta readers
refuse strings that are not valid UTF-8.
"""

from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake

from products.data_modeling.backend.temporal.activities.materialize_view import (
    UnstorableDecimalError,
    UnstorableIntegerError,
    _replace_invalid_utf8,
    _transform_unsigned_integers,
    _transform_unsupported_decimals,
)

Transform = Callable[[pa.RecordBatch], pa.RecordBatch]

WIDE_DECIMAL = pa.decimal256(76, 10)
NARROWED_DECIMAL = pa.decimal128(38, 10)


def _stored(table_path: Path, batch: pa.RecordBatch) -> list:
    deltalake.write_deltalake(str(table_path), batch)
    return deltalake.DeltaTable(str(table_path)).to_pyarrow_table().column("c").to_pylist()


@pytest.mark.parametrize(
    "transform,column,expected_type",
    [
        pytest.param(
            _transform_unsigned_integers, pa.array([200], pa.uint8()), pa.int16(), id="uint8_widens_past_its_signed_max"
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([60000], pa.uint16()),
            pa.int32(),
            id="uint16_widens_past_its_signed_max",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([4000000000], pa.uint32()),
            pa.int64(),
            id="uint32_widens_past_its_signed_max",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([5000000000], pa.uint64()),
            pa.int64(),
            id="uint64_has_no_wider_signed_type",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([[1, 2]], pa.list_(pa.uint64())),
            pa.list_(pa.int64()),
            id="list_value",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([[1, 2]], pa.large_list(pa.uint64())),
            pa.large_list(pa.int64()),
            id="large_list_value",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([{"a": 250}], pa.struct([pa.field("a", pa.uint8())])),
            pa.struct([pa.field("a", pa.int16())]),
            id="struct_field",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([[("k", 7)]], pa.map_(pa.string(), pa.uint32())),
            pa.map_(pa.string(), pa.int64()),
            id="map_value",
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array(["x"], pa.string()),
            pa.string(),
            id="a_type_delta_already_stores_is_untouched",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([Decimal("12.5"), None], WIDE_DECIMAL),
            NARROWED_DECIMAL,
            id="decimal256",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([Decimal("12.5")], pa.decimal256(20, 2)),
            pa.decimal128(20, 2),
            id="decimal256_that_fits_in_128_bits",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([[Decimal("12.5"), None]], pa.list_(WIDE_DECIMAL)),
            pa.list_(NARROWED_DECIMAL),
            id="decimal256_list_value",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([[Decimal("12.5")]], pa.large_list(WIDE_DECIMAL)),
            pa.large_list(NARROWED_DECIMAL),
            id="decimal256_large_list_value",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([{"amount": Decimal("12.5")}], pa.struct([pa.field("amount", WIDE_DECIMAL)])),
            pa.struct([pa.field("amount", NARROWED_DECIMAL)]),
            id="decimal256_struct_field",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([[("k", Decimal("12.5"))]], pa.map_(pa.string(), WIDE_DECIMAL)),
            pa.map_(pa.string(), NARROWED_DECIMAL),
            id="decimal256_map_value",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([[{"amount": Decimal("12.5")}]], pa.list_(pa.struct([pa.field("amount", WIDE_DECIMAL)]))),
            pa.list_(pa.struct([pa.field("amount", NARROWED_DECIMAL)])),
            id="decimal256_in_a_struct_in_a_list",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([Decimal("12.5")], pa.decimal128(38, 2)),
            pa.decimal128(38, 2),
            id="decimal128_is_untouched",
        ),
    ],
)
def test_columns_become_a_type_delta_stores(
    tmp_path: Path, transform: Transform, column: pa.Array, expected_type: pa.DataType
) -> None:
    batch = pa.RecordBatch.from_arrays([column], names=["c"])

    transformed = transform(batch)

    assert transformed.schema.field("c").type.equals(expected_type)
    assert transformed.column("c").to_pylist() == column.to_pylist()
    assert _stored(tmp_path, transformed) == column.to_pylist()


@pytest.mark.parametrize(
    "transform,column,error",
    [
        pytest.param(
            _transform_unsigned_integers, pa.array([2**64 - 1], pa.uint64()), UnstorableIntegerError, id="uint64_scalar"
        ),
        pytest.param(
            _transform_unsigned_integers,
            pa.array([[2**64 - 1]], pa.list_(pa.uint64())),
            UnstorableIntegerError,
            id="uint64_nested_in_a_list",
        ),
        pytest.param(
            _transform_unsupported_decimals,
            pa.array([[Decimal("1" * 40)]], pa.list_(WIDE_DECIMAL)),
            UnstorableDecimalError,
            id="decimal256_nested_in_a_list",
        ),
    ],
)
def test_a_value_too_large_for_delta_names_its_column(
    transform: Transform, column: pa.Array, error: type[UnstorableIntegerError | UnstorableDecimalError]
) -> None:
    batch = pa.RecordBatch.from_arrays([column], names=["hash_id"])

    with pytest.raises(error, match='Column "hash_id"'):
        transform(batch)


def _strings(values: Sequence[bytes | None], *, large: bool = False) -> pa.Array:
    if large:
        return pa.array(values, pa.large_binary()).view(pa.large_string())
    return pa.array(values, pa.binary()).view(pa.string())


INVALID = [b"ok", b"caf\xc3", None, b"\xff\xfe ok"]
REPLACED = ["ok", "caf\ufffd", None, "\ufffd\ufffd ok"]


@pytest.mark.parametrize(
    "column,expected",
    [
        pytest.param(_strings(INVALID), REPLACED, id="string"),
        pytest.param(_strings(INVALID, large=True), REPLACED, id="large_string"),
        pytest.param(
            pa.ListArray.from_arrays(pa.array([0, 2, 4], pa.int32()), _strings(INVALID)),
            [REPLACED[:2], REPLACED[2:]],
            id="list_value",
        ),
        pytest.param(
            pa.ListArray.from_arrays(pa.array([0, 2, 4], pa.int32()), _strings(INVALID)).slice(1),
            [REPLACED[2:]],
            id="sliced_list_value",
        ),
        pytest.param(
            pa.StructArray.from_arrays([_strings(INVALID)], names=["label"]),
            [{"label": value} for value in REPLACED],
            id="struct_field",
        ),
        pytest.param(
            pa.array([[(b"k\xff", b"v")], [(b"k", b"v\xc3")]], pa.map_(pa.binary(), pa.binary())).view(
                pa.map_(pa.string(), pa.string())
            ),
            [[("k\ufffd", "v")], [("k", "v\ufffd")]],
            id="map_key_and_value",
        ),
        pytest.param(
            _strings([b"ok"] * 70_000 + [b"\xff"]),
            ["ok"] * 70_000 + ["\ufffd"],
            id="invalid_value_after_many_valid_ones",
        ),
        pytest.param(_strings([b"caf\xc3\xa9", None]), ["café", None], id="valid_utf8_is_untouched"),
    ],
)
def test_strings_that_are_not_valid_utf8_become_readable(tmp_path: Path, column: pa.Array, expected: list) -> None:
    batch = pa.RecordBatch.from_arrays([column], names=["c"])

    transformed = _replace_invalid_utf8(batch)

    assert transformed.schema.field("c").type.equals(column.type)
    assert _stored(tmp_path, transformed) == expected
