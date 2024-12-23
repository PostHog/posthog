import pyarrow as pa
from posthog.temporal.data_imports.pipelines.sql_database_v2.arrow_helpers import _handle_large_integers
from dlt.common.json import json


def test_handle_large_integers():
    json_str_array = pa.array([None if s is None else json.dumps(_handle_large_integers(s)) for s in [{"a": 2**64}]])

    loaded = json.loads(json_str_array[0].as_py())
    assert loaded["a"] == float(2**64)

    json_str_array = pa.array([None if s is None else json.dumps(_handle_large_integers(s)) for s in [{"a": -(2**64)}]])
    loaded = json.loads(json_str_array[0].as_py())
    assert loaded["a"] == float(-(2**64))
