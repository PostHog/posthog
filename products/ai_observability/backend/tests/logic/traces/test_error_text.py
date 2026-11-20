import json

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.error_text import error_text, is_truthy_json


@parameterized.expand(
    [
        ("missing", "", False),
        ("null", "null", False),
        ("empty string", '""', False),
        ("false", "false", False),
        ("zero", "0", False),
        ("empty array", "[]", False),
        ("empty object", "{}", False),
        ("text", '"boom"', True),
        ("text that reads null", '"null"', True),
        ("true", "true", True),
        ("non-zero number", "-1.5", True),
        ("array", '["boom"]', True),
        ("object", '{"message": "boom"}', True),
    ]
)
def test_is_truthy_json(_name: str, raw: str, expected: bool) -> None:
    assert is_truthy_json(raw) is expected


@parameterized.expand(
    [
        ("text", '"rate limited"', "rate limited"),
        ("object", '{"message": "boom", "code": 429}', '{"message": "boom", "code": 429}'),
        (
            "object with non-ASCII text",
            '{"message": "\\u00e9chec \\u2192 r\\u00e9essayer"}',
            '{"message": "échec → réessayer"}',
        ),
        ("empty string", '""', None),
        ("false", "false", None),
        ("missing", None, None),
        ("long text is cut", json.dumps("x" * 500), "x" * 200),
    ]
)
def test_error_text(_name: str, raw: str | None, expected: str | None) -> None:
    assert error_text(raw) == expected
