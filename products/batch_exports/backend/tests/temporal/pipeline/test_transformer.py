import json
import typing

import pytest

from products.batch_exports.backend.temporal.pipeline.transformer import dump_dict


def create_deeply_nested_dict(depth: int, value: str = "test") -> typing.Any:
    """Create a dict with specified nesting depth."""
    result = value
    for _ in range(depth):
        result = {"nested": result}
    return result


@pytest.mark.parametrize(
    "input_dict, expected_output",
    [
        # orjson doesn't support integers exceeding 64-bit range, so ensure we fall back to json.dumps correctly
        ({"large_integer": 12345678901234567890987654321}, b'{"large_integer": 12345678901234567890987654321}\n'),
        # Complex nested case with datetime and various types
        (
            {
                "timestamp": "2023-01-01T12:00:00Z",
                "nested": {
                    "array": [1, 2, 3],
                    "big_num": 12345678901234567890987654321,
                    "null_value": None,
                    "bool_value": True,
                    "unicode": "Hello 👋 世界",
                },
                "list_of_objects": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}],
            },
            b'{"timestamp": "2023-01-01T12:00:00Z", "nested": {"array": [1, 2, 3], "big_num": 12345678901234567890987654321, "null_value": null, "bool_value": true, "unicode": "Hello \\ud83d\\udc4b \\u4e16\\u754c"}, "list_of_objects": [{"id": 1, "value": "first"}, {"id": 2, "value": "second"}]}\n',
        ),
    ],
)
def test_dump_dict(input_dict, expected_output):
    """Test json_dumps_bytes handles integers exceeding 64-bit range."""
    result = dump_dict(input_dict)
    assert result == expected_output
    assert isinstance(result, bytes)
    # check the reverse direction
    assert json.loads(result) == input_dict


def test_dump_dict_with_deeply_nested_dict():
    """Test dump_dict with a deeply nested dict."""
    deeply_nested_dict = create_deeply_nested_dict(300)
    result = dump_dict(deeply_nested_dict)
    assert result == json.dumps(deeply_nested_dict, default=str).encode("utf-8") + b"\n"
    assert isinstance(result, bytes)
    # check the reverse direction
    assert json.loads(result) == deeply_nested_dict
