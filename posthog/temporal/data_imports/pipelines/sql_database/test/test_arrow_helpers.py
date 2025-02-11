import pytest
import pyarrow as pa
import decimal

from posthog.temporal.data_imports.pipelines.sql_database.arrow_helpers import json_dumps, row_tuples_to_arrow
from dlt.common.json import json


def test_handle_large_integers():
    # Test that orjson raises TypeError for integers outside 64-bit range
    with pytest.raises(TypeError, match="Integer exceeds 64-bit range"):
        json.dumps({"a": 2**64})

    with pytest.raises(TypeError, match="Integer exceeds 64-bit range"):
        json.dumps({"a": -(2**64)})

    json_str_array = pa.array([None if s is None else json_dumps(s) for s in [{"a": 2**64}]])

    loaded = json.loads(json_str_array[0].as_py())
    assert loaded["a"] == float(2**64)

    json_str_array = pa.array([None if s is None else json_dumps(s) for s in [{"a": -(2**64)}]])
    loaded = json.loads(json_str_array[0].as_py())
    assert loaded["a"] == float(-(2**64))


def test_string_infinity_in_decimal():
    # Test data with infinity in decimal field which should be converted to None
    rows = [(decimal.Decimal("Infinity"),), (decimal.Decimal("-Infinity"),)]
    columns = {"value": {"name": "value", "data_type": "decimal", "nullable": True}}

    # Convert to arrow table - should handle infinity by converting to None
    table = row_tuples_to_arrow(rows, columns, "UTC")

    # Check that infinity was converted to None
    assert table.column("value")[0].as_py() is None
