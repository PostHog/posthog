import pytest

from posthog.temporal.data_imports.sources.shopify.utils import safe_unwrap, unwrap


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
