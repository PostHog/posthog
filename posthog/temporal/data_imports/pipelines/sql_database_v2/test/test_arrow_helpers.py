import pytest
import pyarrow as pa
from posthog.temporal.data_imports.pipelines.sql_database_v2.arrow_helpers import json_dumps
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
