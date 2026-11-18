from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.values import JsonValue

from .semantic import canonical


@parameterized.expand(
    [
        ("number notation", {"n": 1}, {"n": 1.0}, True),
        ("a null field and a missing one", {"a": None, "b": 1}, {"b": 1}, True),
        ("JSON text with other spacing and key order", '{"a":1,"b":[2]}', '{ "b": [2], "a": 1.0 }', True),
        ("a boolean and a number", {"n": True}, {"n": 1}, False),
        ("JSON text and the object it encodes", '{"a":1}', {"a": 1}, False),
        ("different text", "a", "b", False),
    ]
)
def test_compares_by_meaning(_name: str, left: JsonValue, right: JsonValue, equal: bool) -> None:
    assert (canonical(left) == canonical(right)) is equal
