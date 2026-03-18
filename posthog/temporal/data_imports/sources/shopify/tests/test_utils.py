from copy import deepcopy

import pytest

from posthog.temporal.data_imports.sources.shopify.constants import resolve_schema_name
from posthog.temporal.data_imports.sources.shopify.utils import safe_set, safe_unwrap, unwrap


@pytest.mark.parametrize(
    "name, expected",
    [
        ("abandonedCheckouts", "abandonedCheckouts"),
        ("discountCodes", "discountNodes"),
    ],
)
def test_resolve_schema_name(name: str, expected: str):
    assert resolve_schema_name(name) == expected


@pytest.fixture
def payload():
    return {"a": {"b": 1}}


def test_unwrap(payload):
    expected = 1
    assert unwrap(payload, path="a.b") == expected

    with pytest.raises(KeyError):
        unwrap(payload, path="a.c")


def test_safe_unwrap(payload):
    expected = 1
    actual, ok = safe_unwrap(payload, path="a.b")
    assert ok
    assert actual == expected

    expected = payload
    actual, ok = safe_unwrap(payload, path="a.c")
    assert not ok
    assert actual == expected


def test_safe_set(payload):
    original = deepcopy(payload)  # safe off an unmodified ref

    payload = deepcopy(original)
    safe_set(payload, path="a", value=2)  # shouldn't overwrite
    assert payload == original

    payload = deepcopy(original)
    safe_set(payload, path="a.b", value=2)  # can traverse and shouldn't overwrite
    assert payload == original

    payload = deepcopy(original)
    safe_set(payload, path="a.b.c", value=2)  # doesn't try to index non-dict items
    assert payload == original

    payload = deepcopy(original)
    payload["test"] = None
    expected = deepcopy(payload)
    safe_set(payload, path="test", value=2)  # doesn't try to overwrite an existing None
    assert payload == expected

    payload = deepcopy(original)
    payload["test"] = None
    expected = deepcopy(payload)
    safe_set(payload, path="test.a", value=2)  # doesn't try to call get() or index into None
    assert payload == expected

    payload = deepcopy(original)
    expected = deepcopy(original)
    expected["test"] = "test"
    safe_set(payload, path="test", value="test")  # can traverse and set when key not present
    assert payload == expected

    payload = deepcopy(original)
    expected = deepcopy(original)
    expected["test"] = {"a": "test"}
    safe_set(payload, path="test.a", value="test")  # can create sub objects to traverse safely
    assert payload == expected
