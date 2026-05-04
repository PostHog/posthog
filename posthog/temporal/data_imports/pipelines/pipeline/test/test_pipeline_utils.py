import uuid
import decimal
import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
import deltalake
import structlog
from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _evolve_pyarrow_schema,
    _get_max_decimal_type,
    append_partition_key_to_table,
    normalize_table_column_names,
    setup_partitioning,
    table_from_py_list,
)
from posthog.temporal.data_imports.pipelines.test_mocks import mock_delta_table


def test_table_from_py_list_uuid():
    uuid_ = uuid.uuid4()
    table = table_from_py_list([{"column": uuid_}])

    assert table.equals(pa.table({"column": [str(uuid_)]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_inconsistent_list():
    table = table_from_py_list([{"column": "hello"}, {"column": ["hi"]}])

    assert table.equals(pa.table({"column": ['["hello"]', '["hi"]']}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_inconsistent_other_types():
    table = table_from_py_list([{"column": "hello"}, {"column": 12}])

    assert table.equals(pa.table({"column": ['"hello"', "12"]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_inconsistent_types_with_none():
    table = table_from_py_list([{"column": None}, {"column": "hello"}, {"column": 12}, {"column": None}])

    assert table.equals(pa.table({"column": [None, '"hello"', "12", None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_inconsistent_types_with_str_and_dict():
    table = table_from_py_list([{"column": "hello"}, {"column": {"field": 1}}])

    assert table.equals(pa.table({"column": ["hello", '{"field":1}']}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_with_lists():
    table = table_from_py_list([{"column": ["hello"]}, {"column": ["hi"]}])

    assert table.equals(pa.table({"column": ['["hello"]', '["hi"]']}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_with_nan():
    table = table_from_py_list([{"column": 1.0}, {"column": float("NaN")}])

    assert table.equals(pa.table({"column": [1.0, None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.float64()),
            ]
        )
    )


def test_table_from_py_list_with_inf():
    table = table_from_py_list([{"column": 1.0}, {"column": float("Inf")}])

    assert table.equals(pa.table({"column": [1.0, None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.float64()),
            ]
        )
    )


def test_table_from_py_list_with_negative_inf():
    table = table_from_py_list([{"column": 1.0}, {"column": -float("Inf")}])

    assert table.equals(pa.table({"column": [1.0, None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.float64()),
            ]
        )
    )


def test_table_from_py_list_with_decimal_inf():
    table = table_from_py_list([{"column": decimal.Decimal(1)}, {"column": decimal.Decimal("Infinity")}])

    assert table.equals(pa.table({"column": [decimal.Decimal("1.0"), None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.decimal128(2, 1)),
            ]
        )
    )


def test_table_from_py_list_with_negative_decimal_inf():
    table = table_from_py_list([{"column": decimal.Decimal(1)}, {"column": decimal.Decimal("-Infinity")}])

    assert table.equals(pa.table({"column": [decimal.Decimal("1.0"), None]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.decimal128(2, 1)),
            ]
        )
    )


def test_table_from_py_list_with_binary_column():
    table = table_from_py_list([{"column": 1.0, "some_bytes": b"hello"}])

    assert table.equals(pa.table({"column": [1.0]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.float64()),
            ]
        )
    )


def test_table_from_py_list_with_null_filled_binary_column():
    schema = pa.schema(cast(Any, [pa.field("column", pa.string()), pa.field("some_bytes", pa.binary())]))
    table = table_from_py_list([{"column": "hello", "some_bytes": None}], schema)

    assert table.equals(pa.table({"column": ["hello"]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_with_mixed_decimal_float_sizes():
    table = table_from_py_list([{"column": decimal.Decimal(1.0)}, {"column": 1000.01}])

    expected_schema = pa.schema({"column": pa.decimal128(6, 2)})
    assert table.equals(
        pa.table(
            {"column": pa.array([decimal.Decimal("1.0"), decimal.Decimal(str(1000.01))], type=pa.decimal128(6, 2))},
            schema=expected_schema,
        )
    )
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.decimal128(6, 2)),
            ]
        )
    )


def test_table_from_py_list_with_schema_and_mixed_decimals():
    schema = pa.schema({"column": pa.decimal128(1, 0)})
    table = table_from_py_list([{"column": 1}, {"column": 1.0}], schema)

    assert table.equals(pa.table({"column": [decimal.Decimal(1), decimal.Decimal(1)]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.decimal128(1, 0)),
            ]
        )
    )


def test_table_from_py_list_with_schema_and_str_timestamp():
    schema = pa.schema({"column": pa.timestamp("us")})
    table = table_from_py_list([{"column": "2024-01-01T00:00:00"}], schema)

    expected_schema = pa.schema([pa.field("column", pa.timestamp("us"), nullable=False)])
    assert table.equals(
        pa.table(
            {"column": pa.array([parser.parse("2024-01-01T00:00:00")], type=pa.timestamp("us"))}, schema=expected_schema
        )
    )
    assert table.schema.equals(expected_schema)


def test_table_from_py_list_with_schema_and_too_small_decimal_type():
    schema = pa.schema({"column": pa.decimal128(3, 3)})
    table = table_from_py_list([{"column": decimal.Decimal("1.001")}], schema)

    expected_schema = pa.schema([pa.field("column", pa.decimal128(4, 3))])
    assert table.equals(pa.table({"column": pa.array([decimal.Decimal("1.001")], type=pa.decimal128(4, 3))}))
    assert table.schema.equals(expected_schema)


@pytest.mark.parametrize(
    "decimals,expected",
    [
        ([decimal.Decimal("1")], pa.decimal128(2, 1)),
        ([decimal.Decimal("1.001112")], pa.decimal128(7, 6)),
        ([decimal.Decimal("0.001112")], pa.decimal128(6, 6)),
        ([decimal.Decimal("1.0100000")], pa.decimal128(8, 7)),
        # That is 1 followed by 37 zeroes to go over the pa.Decimal128 precision limit of 38.
        ([decimal.Decimal("10000000000000000000000000000000000000.1")], pa.decimal256(39, 1)),
    ],
)
def test_get_max_decimal_type_returns_correct_decimal_type(
    decimals: list[decimal.Decimal],
    expected: pa.Decimal128Type | pa.Decimal256Type,
):
    """Test whether expected PyArrow decimal type variant is returned."""
    result = _get_max_decimal_type(decimals)
    assert result == expected


def test_table_from_py_list_with_ipv4_address():
    table = table_from_py_list([{"column": IPv4Address("127.0.0.1")}])

    assert table.equals(pa.table({"column": ["127.0.0.1"]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_table_from_py_list_with_ipv6_address():
    table = table_from_py_list([{"column": IPv6Address("::1")}])

    assert table.equals(pa.table({"column": ["::1"]}))
    assert table.schema.equals(
        pa.schema(
            [
                ("column", pa.string()),
            ]
        )
    )


def test_normalize_table_column_names_prevents_collisions():
    # Create a table with columns that would collide when normalized
    table = pa.table({"foo___bar": ["value1"], "foo_bar": ["value2"], "another___field": ["value3"]})

    normalized_table = normalize_table_column_names(table)

    # First column gets normalized
    assert "foo_bar" in normalized_table.column_names
    # Second column that would collide gets underscore prefix
    assert "_foo_bar" in normalized_table.column_names
    # Non-colliding column gets normalized
    assert "another_field" in normalized_table.column_names

    # Verify the data is preserved
    assert normalized_table.column("foo_bar").to_pylist() == ["value2"]
    assert normalized_table.column("_foo_bar").to_pylist() == ["value1"]
    assert normalized_table.column("another_field").to_pylist() == ["value3"]


def test_table_from_py_list_with_rescaling_decimal_data_loss_error():
    # Very restrictive type, and the large_decimal value is too large for the schema
    schema = pa.schema({"column": pa.decimal128(5, 1)})
    large_decimal = decimal.Decimal("12345.6789")

    table = table_from_py_list([{"column": large_decimal}], schema)

    expected_schema = pa.schema([pa.field("column", pa.decimal128(9, 4))])
    assert table.equals(pa.table({"column": pa.array([decimal.Decimal("12345.6789")], type=pa.decimal128(9, 4))}))
    assert table.schema.equals(expected_schema)


@pytest.mark.parametrize(
    "data, schema, expected_type",
    [
        ([{"column": decimal.Decimal("1234567.5")}], pa.schema({"column": pa.decimal128(38, 32)}), pa.decimal128(8, 1)),
        (
            [{"column": decimal.Decimal("999999.99")}],
            pa.schema({"column": pa.decimal128(38, 32)}),
            pa.decimal128(38, 32),
        ),
        ([{"column": decimal.Decimal("1" * 39 + ".1")}], pa.schema({"column": pa.decimal128(5, 1)}), None),
        (
            [{"column": decimal.Decimal("1234567.5")}, {"column": None}],
            pa.schema({"column": pa.decimal128(38, 32)}),
            pa.decimal128(8, 1),
        ),
    ],
)
def test_table_from_py_list_decimal_fallback_optimal_type(data, schema, expected_type):
    """table_from_py_list picks minimal decimal type from values; decimal256 only when precision > 38."""
    table = table_from_py_list(data, schema)
    col_type = table.schema.field("column").type
    if expected_type is not None:
        assert col_type == expected_type
    else:
        assert pa.types.is_decimal256(col_type)


@pytest.mark.parametrize(
    "batch_type, batch_values, delta_type, expected_type, expect_string",
    [
        (
            pa.decimal128(10, 2),
            [decimal.Decimal("12.5"), decimal.Decimal("89.0")],
            pa.decimal128(38, 2),
            pa.decimal128(38, 2),
            False,
        ),
        (
            pa.decimal256(76, 32),
            [decimal.Decimal("1234567.5"), decimal.Decimal("89.0")],
            pa.decimal128(38, 32),
            None,
            True,
        ),
        (
            pa.decimal128(10, 2),
            [decimal.Decimal("12345678.01"), decimal.Decimal("1.00")],
            pa.decimal128(38, 32),
            pa.decimal128(38, 30),
            False,
        ),
        (pa.decimal128(5, 2), [decimal.Decimal("123.45")], pa.decimal128(38, 32), pa.decimal128(38, 32), False),
        (pa.decimal256(76, 0), [decimal.Decimal("1" * 39)], pa.decimal128(38, 32), None, True),
        (pa.decimal128(5, 2), [decimal.Decimal("123.45"), None], pa.decimal128(38, 32), pa.decimal128(38, 32), False),
        (
            pa.decimal128(38, 5),
            [decimal.Decimal("123456789012345678901234567890123")],
            pa.decimal128(38, 10),
            pa.decimal128(38, 5),
            False,
        ),
    ],
)
def test_evolve_pyarrow_schema_decimal_reconciliation(
    batch_type, batch_values, delta_type, expected_type, expect_string
):
    """Decimal reconciliation: merge to decimal128(38, scale) when fits, else decimal256→string."""
    arrow_table = pa.table(
        {"id": pa.array([1] * len(batch_values), type=pa.int64()), "amount": pa.array(batch_values, type=batch_type)}
    )
    delta_schema = deltalake.Schema.from_arrow(
        pa.schema([pa.field("id", pa.int64(), nullable=False), pa.field("amount", delta_type, nullable=True)])
    )
    evolved = _evolve_pyarrow_schema(arrow_table, delta_schema)
    result_type = evolved.schema.field("amount").type
    result_vals = evolved.column("amount").to_pylist()
    if expect_string:
        assert pa.types.is_string(result_type)
        for orig, got in zip(batch_values, result_vals):
            if orig is not None:
                assert got is not None and decimal.Decimal(str(got)) == orig
    else:
        assert result_type == expected_type
        for orig, got in zip(batch_values, result_vals):
            if orig is not None and got is not None:
                assert abs(got - orig) < decimal.Decimal("0.001")


def test_evolve_pyarrow_schema_arrow_invalid_fallback_to_decimal256_then_string():
    """ArrowInvalid on decimal128 cast (e.g. rescale data loss) → column becomes decimal256 then string."""
    value = decimal.Decimal("0.12345678901234567890123456789012")
    arrow_table = pa.table(
        {
            "id": pa.array([1], type=pa.int64()),
            "amount": pa.array([value], type=pa.decimal128(38, 32)),
        }
    )
    delta_fields: list[pa.Field] = [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("amount", pa.decimal128(38, 18), nullable=True),
    ]
    delta_schema = deltalake.Schema.from_arrow(pa.schema(delta_fields))
    evolved_table = _evolve_pyarrow_schema(arrow_table, delta_schema)
    result_type = evolved_table.schema.field("amount").type
    assert pa.types.is_string(result_type)
    result_val = evolved_table.column("amount").to_pylist()[0]
    assert result_val is not None
    assert decimal.Decimal(result_val) == value


def test_evolve_pyarrow_schema_decimal_integration_table_from_py_list():
    """table_from_py_list + _evolve_pyarrow_schema: 7 int digits → decimal128(38, 31)."""
    schema = pa.schema({"amount": pa.decimal128(38, 32)})
    table = table_from_py_list([{"amount": decimal.Decimal("1234567.5")}], schema)
    delta_fields: list[pa.Field] = [
        pa.field("amount", pa.decimal128(38, 32), nullable=True),
    ]
    delta_schema = deltalake.Schema.from_arrow(pa.schema(delta_fields))
    evolved_table = _evolve_pyarrow_schema(table, delta_schema)
    assert evolved_table.schema.field("amount").type == pa.decimal128(38, 31)


@pytest.mark.parametrize(
    "incoming_type, incoming_values, expected_type",
    [
        (
            pa.decimal128(10, 2),
            [decimal.Decimal("12.50"), decimal.Decimal("89.00")],
            pa.decimal128(10, 2),
        ),
        (
            pa.decimal128(38, 2),
            [decimal.Decimal("12.50"), decimal.Decimal("89.00")],
            pa.decimal128(10, 2),
        ),
        (
            pa.decimal128(38, 2),
            [decimal.Decimal("12345678901.23"), decimal.Decimal("89.00")],
            pa.decimal128(38, 2),
        ),
        (
            pa.decimal128(10, 3),
            [decimal.Decimal("1234567.123"), decimal.Decimal("89.00")],
            pa.decimal128(11, 3),
        ),
    ],
)
def test_evolve_pyarrow_schema_decimal_does_not_widen_unnecessarily_and_can_widen_when_needed(
    incoming_type: pa.Decimal128Type, incoming_values: list[decimal.Decimal], expected_type: pa.Decimal128Type
):
    arrow_table = pa.table(
        {
            "id": pa.array([1, 2], type=pa.int64()),
            "amount": pa.array(incoming_values, type=incoming_type),
        }
    )
    delta_schema = deltalake.Schema.from_arrow(
        pa.schema([pa.field("id", pa.int64(), nullable=False), pa.field("amount", pa.decimal128(10, 2), nullable=True)])  # type: ignore[arg-type]
    )

    evolved_table = _evolve_pyarrow_schema(arrow_table, delta_schema)

    assert evolved_table.schema.field("amount").type == expected_type


def test_evolve_pyarrow_schema_with_struct_containing_datetime_and_decimal():
    """Test that _evolve_pyarrow_schema can handle struct columns with non-JSON-serializable types."""
    metadata_struct_type = pa.struct(
        [
            ("role", pa.string()),
            ("hire_date", pa.timestamp("us")),
            ("salary", pa.decimal128(10, 2)),
        ]
    )

    metadata_data = [
        {
            "role": "admin",
            "hire_date": datetime.datetime(2020, 1, 15, 10, 30, 0),
            "salary": decimal.Decimal("75000.50"),
        },
        {"role": "user", "hire_date": datetime.datetime(2021, 3, 20, 9, 0, 0), "salary": decimal.Decimal("65000.00")},
    ]

    arrow_table = pa.table(
        {
            "id": pa.array([1, 2], type=pa.int64()),
            "metadata": pa.array(metadata_data, type=metadata_struct_type),
        }
    )

    delta_fields: list[pa.Field] = [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("metadata", pa.string(), nullable=True),
    ]
    delta_schema = deltalake.Schema.from_arrow(pa.schema(delta_fields))
    evolved_table = _evolve_pyarrow_schema(arrow_table, delta_schema)

    assert evolved_table.schema.field("metadata").type == pa.string()
    metadata_values = evolved_table.column("metadata").to_pylist()
    assert len(metadata_values) == 2
    assert all(isinstance(val, str) for val in metadata_values)


def test_evolve_pyarrow_schema_with_list_containing_datetime():
    """Test that _evolve_pyarrow_schema can handle list columns with non-JSON-serializable types."""
    arrow_table = pa.table(
        {
            "id": pa.array([1, 2], type=pa.int64()),
            "tags": pa.array([["python", "data"], ["sales", "crm"]], type=pa.list_(pa.string())),
        }
    )

    delta_fields: list[pa.Field] = [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("tags", pa.string(), nullable=True),
    ]
    delta_schema = deltalake.Schema.from_arrow(pa.schema(delta_fields))

    evolved_table = _evolve_pyarrow_schema(arrow_table, delta_schema)

    assert evolved_table.schema.field("tags").type == pa.string()
    tags_values = evolved_table.column("tags").to_pylist()
    assert len(tags_values) == 2
    assert all(isinstance(val, str) for val in tags_values)


class TestEvolveSchemaFirstPass:
    """First pass: normalize incoming table types before delta alignment."""

    def test_no_delta_schema_returns_delta_compatible_table(self):
        arrow_table = pa.table({"id": pa.array([1], type=pa.int64()), "name": pa.array(["a"])})
        result = _evolve_pyarrow_schema(arrow_table, None)
        assert result.schema.field("id").type == pa.int64()
        assert result.schema.field("name").type in (pa.string(), pa.large_string())

    def test_duration_column_converted_to_seconds(self):
        durations = pa.array([datetime.timedelta(seconds=90), datetime.timedelta(seconds=3661), None])
        arrow_table = pa.table({"elapsed": durations})
        result = _evolve_pyarrow_schema(arrow_table, None)
        values = result.column("elapsed").to_pylist()
        assert values[0] == 90.0
        assert values[1] == 3661.0
        assert values[2] is None

    def test_nanosecond_timestamp_normalized_to_microseconds(self):
        ns_ts = pa.array([1_000_000_000, 2_000_000_000], type=pa.timestamp("ns"))
        arrow_table = pa.table({"ts": ns_ts})
        result = _evolve_pyarrow_schema(arrow_table, None)
        assert result.schema.field("ts").type == pa.timestamp("us")

    def test_tz_timestamp_stripped_to_utc_microseconds(self):
        tz_ts = pa.array([1_000_000, 2_000_000], type=pa.timestamp("us", tz="America/New_York"))
        arrow_table = pa.table({"ts": tz_ts})
        result = _evolve_pyarrow_schema(arrow_table, None)
        assert result.schema.field("ts").type == pa.timestamp("us")
        assert result.schema.field("ts").type.tz is None


class TestEvolveSchemaSecondPassMissingColumns:
    """Second pass: columns present in delta but missing from incoming table."""

    def test_missing_nullable_column_appended_with_nulls(self):
        arrow_table = pa.table({"id": pa.array([1, 2], type=pa.int64())})
        delta_schema = deltalake.Schema.from_arrow(
            pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string(), nullable=True)])  # type: ignore[arg-type]
        )
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        assert "name" in result.column_names
        assert result.column("name").to_pylist() == [None, None]

    def test_missing_non_nullable_column_appended_with_defaults(self):
        arrow_table = pa.table({"id": pa.array([1, 2], type=pa.int64())})
        delta_schema = deltalake.Schema.from_arrow(
            pa.schema([pa.field("id", pa.int64()), pa.field("count", pa.int64(), nullable=False)])
        )
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        assert "count" in result.column_names
        assert result.column("count").to_pylist() == [0, 0]


class TestEvolveSchemaSecondPassDecimal:
    """Second pass: decimal reconciliation between incoming and delta types."""

    def test_downcast_skipped_when_scales_differ(self):
        arrow_table = pa.table({"amount": pa.array([decimal.Decimal("1.50")], type=pa.decimal128(38, 4))})
        delta_schema = deltalake.Schema.from_arrow(pa.schema([pa.field("amount", pa.decimal128(10, 2), nullable=True)]))
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        result_type = result.schema.field("amount").type
        assert pa.types.is_decimal128(result_type)
        # max_int_digits = max(8, 34) = 34, merged_scale = min(max(2,4), 38-34) = 4, precision = 38
        assert result_type == pa.decimal128(38, 4)


class TestEvolveSchemaSecondPassTimestamp:
    """Second pass: timestamp alignment between incoming and delta types."""

    def test_timestamp_tz_mismatch_casted(self):
        utc_ts = pa.array([datetime.datetime(2024, 1, 1, 0, 0, 0)], type=pa.timestamp("us", tz="UTC"))
        arrow_table = pa.table({"ts": utc_ts})
        delta_schema = deltalake.Schema.from_arrow(pa.schema([pa.field("ts", pa.timestamp("us"), nullable=True)]))
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        assert result.schema.field("ts").type == pa.timestamp("us")
        assert result.schema.field("ts").type.tz is None

    def test_string_column_parsed_to_delta_timestamp(self):
        arrow_table = pa.table({"ts": pa.array(["2024-01-01T12:00:00", "2024-06-15T08:30:00"])})
        delta_schema = deltalake.Schema.from_arrow(pa.schema([pa.field("ts", pa.timestamp("us"), nullable=True)]))
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        assert result.schema.field("ts").type == pa.timestamp("us")
        values = result.column("ts").to_pylist()
        assert values[0] == datetime.datetime(2024, 1, 1, 12, 0, 0)
        assert values[1] == datetime.datetime(2024, 6, 15, 8, 30, 0)


class TestEvolveSchemaSecondPassGenericCast:
    """Second pass: non-decimal, non-timestamp type mismatches."""

    def test_int32_casted_to_int64(self):
        arrow_table = pa.table({"count": pa.array([1, 2, 3], type=pa.int32())})
        delta_schema = deltalake.Schema.from_arrow(pa.schema([pa.field("count", pa.int64(), nullable=True)]))
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        assert result.schema.field("count").type == pa.int64()
        assert result.column("count").to_pylist() == [1, 2, 3]


class TestEvolveSchemaSecondPassNullability:
    """Second pass: nullable incoming column aligned to non-nullable delta field."""

    def test_nullable_incoming_backfilled_for_non_nullable_delta(self):
        arrow_table = pa.table({"name": pa.array(["hello", None, "world"])})
        delta_schema = deltalake.Schema.from_arrow(pa.schema([pa.field("name", pa.large_string(), nullable=False)]))
        result = _evolve_pyarrow_schema(arrow_table, delta_schema)
        values = result.column("name").to_pylist()
        assert values == ["hello", "", "world"]


@pytest.mark.parametrize(
    "name, data",
    [
        ("incrementing_ints_dense", [1, 2, 3, 4, 5]),
        ("incrementing_ints_sparse", [1, 100]),
        ("all_nulls", [None, None, None]),
    ],
)
def test_append_partition_key_to_table_does_not_type_error(name: str, data: list[Any]):
    partition_key = "id"
    table = pa.table({partition_key: data})

    logger: FilteringBoundLogger = structlog.get_logger()

    try:
        append_partition_key_to_table(
            table,
            partition_keys=[partition_key],
            partition_mode=None,
            partition_count=None,
            partition_size=None,
            partition_format=None,
            logger=logger,
        )
    except TypeError:
        pytest.fail(f"raised TypeError for case {name} with data: {data}")


def _mock_schema(**overrides: Any) -> MagicMock:
    schema = MagicMock()
    schema.partition_count = overrides.get("partition_count")
    schema.partition_size = overrides.get("partition_size")
    schema.partitioning_keys = overrides.get("partitioning_keys")
    schema.partition_format = overrides.get("partition_format")
    schema.partition_mode = overrides.get("partition_mode")
    schema.partitioning_enabled = overrides.get("partitioning_enabled", True)
    schema.set_partitioning_enabled = MagicMock()
    return schema


def _mock_resource(**overrides: Any) -> MagicMock:
    resource = MagicMock()
    resource.partition_count = overrides.get("partition_count")
    resource.partition_size = overrides.get("partition_size")
    resource.partition_keys = overrides.get("partition_keys")
    resource.primary_keys = overrides.get("primary_keys")
    resource.partition_format = overrides.get("partition_format")
    resource.partition_mode = overrides.get("partition_mode")
    return resource


# Regression coverage for the `DeltaError: Specified table partitioning does not match` bug.
#
# When an existing delta table contains `_ph_partition_key` in its *schema columns*
# but not in its *partition columns* (e.g. left over from a write committed with
# `partition_by=None`), subsequent writes with `partition_by=PARTITION_KEY` raise:
#
#     DeltaError: Generic error: Specified table partitioning does not match
#     table partitioning: expected: [], got: ["_ph_partition_key"]
#
# The fix checks `delta_table.metadata().partition_columns` rather than the
# table's schema columns when deciding whether to add the partition key.
_COL_ID = pa.field("id", pa.int64())
_COL_PARTITION = pa.field(PARTITION_KEY, pa.string())


@pytest.mark.parametrize(
    "case,schema_fields,partition_columns,expect_key",
    [
        # Column in schema but NOT in partition_columns → skip (the exact bug scenario).
        ("column_in_schema_not_partitioned", [_COL_ID, _COL_PARTITION], [], False),
        # `metadata().partition_columns` returning None → skip defensively.
        ("partition_columns_is_none", [_COL_ID, _COL_PARTITION], None, False),
        # Truly partitioned by `_ph_partition_key` → happy path, partitioning applies.
        ("table_partitioned_by_key", [_COL_ID, _COL_PARTITION], [PARTITION_KEY], True),
        # Legacy unpartitioned table without the column at all → skip.
        ("column_missing_entirely", [_COL_ID], [], False),
    ],
)
@pytest.mark.asyncio
async def test_setup_partitioning_respects_existing_delta_partition_columns(
    case: str,
    schema_fields: list[pa.Field],
    partition_columns: list[str] | None,
    expect_key: bool,
):
    logger: FilteringBoundLogger = structlog.get_logger()
    pa_table = pa.table({"id": [1, 2, 3]})
    delta_table = mock_delta_table(schema_fields=schema_fields, partition_columns=partition_columns)

    # For the happy-path case we need the schema mock to look "already aligned" so that
    # `set_partitioning_enabled` isn't invoked (which would require DB integration).
    schema_kwargs: dict[str, Any] = {"partitioning_keys": ["id"]}
    if expect_key:
        schema_kwargs.update(partition_mode="md5", partition_format=None)
    resource_kwargs: dict[str, Any] = {"partition_keys": ["id"]}
    if expect_key:
        resource_kwargs["partition_count"] = 10

    result = await setup_partitioning(
        pa_table=pa_table,
        existing_delta_table=delta_table,
        schema=_mock_schema(**schema_kwargs),
        resource=_mock_resource(**resource_kwargs),
        logger=logger,
    )

    if expect_key:
        assert PARTITION_KEY in result.column_names, case
    else:
        assert PARTITION_KEY not in result.column_names, case
        assert result.equals(pa_table), case


@pytest.mark.asyncio
async def test_setup_partitioning_no_delta_table_no_partition_keys_returns_unchanged():
    logger: FilteringBoundLogger = structlog.get_logger()
    pa_table = pa.table({"id": [1, 2, 3]})

    result = await setup_partitioning(
        pa_table=pa_table,
        existing_delta_table=None,
        schema=_mock_schema(),
        resource=_mock_resource(),
        logger=logger,
    )

    assert result.equals(pa_table)
    assert PARTITION_KEY not in result.column_names
