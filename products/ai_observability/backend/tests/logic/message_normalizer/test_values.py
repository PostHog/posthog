from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.values import (
    MISSING,
    Value,
    has_field,
    is_truthy,
    read_field,
    read_path,
    strict_equals,
    to_json_value,
    to_text,
)


def test_reads_a_present_field_and_walks_nested_segments() -> None:
    assert read_field({"role": "user"}, "role") == "user"
    assert read_path({"a": {"b": {"c": 1}}}, ["a", "b", "c"]) == 1


def test_a_null_field_is_present() -> None:
    assert has_field({"role": "user"}, "role")
    assert has_field({"role": None}, "role")


@parameterized.expand(
    [
        ("missing key", {"a": 1}, "missing"),
        ("string cursor", "not an object", "length"),
        ("list cursor, non-index text", ["a"], "x"),
        ("list cursor, out of range", ["a"], "1"),
        ("list cursor, padded index", ["a", "b"], "01"),
        ("list cursor, signed index", ["a", "b"], "-1"),
    ]
)
def test_reads_missing_for_absent_keys_and_non_mappings(_name: str, value: Value, field: str) -> None:
    assert read_field(value, field) is MISSING
    assert not has_field(value, field)


@parameterized.expand([("first", "0", "a"), ("last", "1", "b")])
def test_read_field_indexes_a_list_with_a_numeric_string(_name: str, field: str, expected: str) -> None:
    assert read_field(["a", "b"], field) == expected


def test_read_path_stops_at_a_missing_segment() -> None:
    assert read_path({"a": {}}, ["a", "b", "c"]) is MISSING


@parameterized.expand([(True, 1), (False, 0), (1, True), ([1], [1]), ({"a": 1}, {"a": 1}), (None, MISSING)])
def test_strict_equals_rejects_what_javascript_rejects(left: Value, right: Value) -> None:
    assert not strict_equals(left, right)


@parameterized.expand([(1, 1.0), ("a", "a"), (None, None), (True, True)])
def test_strict_equals_accepts_same_primitives(left: Value, right: Value) -> None:
    assert strict_equals(left, right)


@parameterized.expand(
    [
        ([], True),
        ({}, True),
        ("x", True),
        (0.5, True),
        ("", False),
        (0, False),
        (0.0, False),
        (False, False),
        (None, False),
        (MISSING, False),
    ]
)
def test_truthiness_follows_javascript(value: Value, expected: bool) -> None:
    assert is_truthy(value) is expected


@parameterized.expand(
    [
        ("text", "hi", "hi"),
        ("missing", MISSING, ""),
        ("null", None, ""),
        ("number", 2, "2"),
        ("boolean", True, "true"),
        ("object", {"a": "é"}, '{"a":"é"}'),
        ("list", [1, "b"], '[1,"b"]'),
    ]
)
def test_to_text_renders_values_as_display_text(_name: str, value: Value, expected: str) -> None:
    assert to_text(value) == expected


def test_to_json_value_strips_the_sentinel() -> None:
    assert to_json_value({"a": MISSING, "b": [MISSING, 1], "c": {"d": MISSING}}) == {"b": [None, 1], "c": {}}
