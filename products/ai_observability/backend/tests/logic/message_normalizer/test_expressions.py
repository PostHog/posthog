import json

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.expressions import (
    ArrayExpr,
    CoalesceExpr,
    Expr,
    InterpExpr,
    JoinExpr,
    LiteralExpr,
    ObjectExpr,
    OmitExpr,
    PathExpr,
    RejectExpr,
    SelectExpr,
    SelfExpr,
    StringifyExpr,
    TryParseStructuredContentExpr,
)
from products.ai_observability.backend.logic.message_normalizer.predicates import EqualsPredicate, Pattern
from products.ai_observability.backend.logic.message_normalizer.run_limits import MAX_PARSE_CHARS
from products.ai_observability.backend.logic.message_normalizer.scope import Scope
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, Value

SCOPE = Scope.for_node({"name": "Ada", "lang": "Hog", "nothing": None, "message": {"content": "hello"}}, "user")
ITEMS = [
    {"type": "text", "text": "keep me"},
    {"type": "image", "text": "drop me"},
    {"type": "text", "text": "keep me too"},
]


def lit(value: Value) -> LiteralExpr:
    return LiteralExpr(value=value)


def where_type(type_name: str) -> Pattern:
    return Pattern(fields=(("type", EqualsPredicate(expected=type_name)),))


@parameterized.expand(
    [
        ("literal string", lit("hello"), "hello"),
        ("literal object", lit({"a": 1}), {"a": 1}),
        ("literal zero", lit(0), 0),
        ("literal empty string", lit(""), ""),
        ("literal false", lit(False), False),
        ("literal null", lit(None), None),
        ("self", SelfExpr(), SCOPE.value),
        ("nested path", PathExpr(segments=("message", "content")), "hello"),
        ("missing nested path", PathExpr(segments=("message", "missing")), MISSING),
        ("missing root path", PathExpr(segments=("missing", "deep")), MISSING),
        ("array", ArrayExpr(items=(lit(1), PathExpr(segments=("name",)))), [1, "Ada"]),
        (
            "object",
            ObjectExpr(fields=(("kind", lit("person")), ("label", PathExpr(segments=("name",))))),
            {"kind": "person", "label": "Ada"},
        ),
        ("empty object", ObjectExpr(fields=()), {}),
        (
            "interpolation",
            InterpExpr(parts=(PathExpr(segments=("name",)), " writes ", PathExpr(segments=("lang",)))),
            "Ada writes Hog",
        ),
        (
            "interpolation of null and missing",
            InterpExpr(parts=("name: ", PathExpr(segments=("nothing",)), PathExpr(segments=("missing",)))),
            "name: ",
        ),
        ("interpolation of a non-string", InterpExpr(parts=("n=", lit(2), " ok=", lit(True))), "n=2 ok=true"),
    ]
)
def test_evaluates(_name: str, expr: Expr, expected: Value) -> None:
    assert expr.eval(SCOPE) == expected


@parameterized.expand(
    [
        ("first non-nullish", (None, MISSING, "chosen", "later"), "chosen"),
        ("keeps zero", (None, 0, "later"), 0),
        ("keeps an empty string", (MISSING, "", "later"), ""),
        ("nothing usable", (None, MISSING), MISSING),
    ]
)
def test_coalesce(_name: str, candidates: tuple[Value, ...], expected: Value) -> None:
    assert CoalesceExpr(source=ArrayExpr(items=tuple(lit(c) for c in candidates))).eval(SCOPE) == expected


@parameterized.expand(
    [
        ("with a separator", JoinExpr(source=lit(["a", "b", "c"]), sep=lit(", "), field=None), "a, b, c"),
        ("newline by default", JoinExpr(source=lit(["a", "b"]), sep=None, field=None), "a\nb"),
        (
            "plucking a field",
            JoinExpr(source=lit([{"text": "one"}, {"text": "two"}, {}]), sep=lit(" / "), field=lit("text")),
            "one / two / ",
        ),
        ("a non-list source", JoinExpr(source=lit("not an array"), sep=lit(", "), field=None), ""),
        (
            "non-string items as text",
            JoinExpr(source=lit([1, True, None, {"a": 1}]), sep=lit(","), field=None),
            '1,true,,{"a":1}',
        ),
    ]
)
def test_join(_name: str, expr: JoinExpr, expected: str) -> None:
    assert expr.eval(SCOPE) == expected


def test_omit_copies_without_the_listed_keys() -> None:
    source = {"a": 1, "b": 2, "c": 3}
    assert OmitExpr(source=lit(source), keys=lit(["b"])).eval(SCOPE) == {"a": 1, "c": 3}
    assert source == {"a": 1, "b": 2, "c": 3}


@parameterized.expand([("string", "nope"), ("list", [1, 2])])
def test_omit_returns_an_empty_object_for_a_non_mapping(_name: str, source: Value) -> None:
    assert OmitExpr(source=lit(source), keys=lit(["b"])).eval(SCOPE) == {}


@parameterized.expand(
    [
        (
            "keeps matches",
            SelectExpr(source=lit(ITEMS), where=where_type("text"), pluck=None, if_empty=None),
            [ITEMS[0], ITEMS[2]],
        ),
        (
            "plucks from matches",
            SelectExpr(source=lit(ITEMS), where=where_type("text"), pluck=PathExpr(segments=("text",)), if_empty=None),
            ["keep me", "keep me too"],
        ),
        (
            "drops null and missing plucks",
            SelectExpr(
                source=lit([{"text": None}, {"text": "a"}, {}]),
                where=None,
                pluck=PathExpr(segments=("text",)),
                if_empty=None,
            ),
            ["a"],
        ),
        (
            "falls back when nothing matches",
            SelectExpr(source=lit(ITEMS), where=where_type("audio"), pluck=None, if_empty=lit("fallback")),
            "fallback",
        ),
        (
            "a null fallback drops the slot",
            SelectExpr(source=lit(ITEMS), where=where_type("audio"), pluck=None, if_empty=lit(None)),
            MISSING,
        ),
        ("a non-list source", SelectExpr(source=lit("nope"), where=None, pluck=None, if_empty=None), []),
        (
            "a non-list source with a fallback",
            SelectExpr(source=lit("nope"), where=None, pluck=None, if_empty=lit("fallback")),
            "fallback",
        ),
        ("rejects matches", RejectExpr(source=lit(ITEMS[:2]), where=where_type("image"), if_empty=None), [ITEMS[0]]),
        (
            "falls back when everything is rejected",
            RejectExpr(source=lit([{"type": "text"}]), where=where_type("text"), if_empty=lit("fallback")),
            "fallback",
        ),
        ("reject on a non-list source", RejectExpr(source=lit("nope"), where=None, if_empty=None), []),
        (
            "reject on a non-list source with a fallback",
            RejectExpr(source=lit("nope"), where=None, if_empty=lit("fallback")),
            "fallback",
        ),
    ]
)
def test_filters(_name: str, expr: Expr, expected: Value) -> None:
    assert expr.eval(SCOPE) == expected


@parameterized.expand(
    [
        ("an object as JSON", {"a": 1, "b": "two"}, '{"a":1,"b":"two"}'),
        ("a string unchanged", "plain", "plain"),
        ("null unchanged", None, None),
        ("missing unchanged", MISSING, MISSING),
        ("a list unchanged", ["a", "b"], ["a", "b"]),
    ]
)
def test_stringify(_name: str, value: Value, expected: Value) -> None:
    assert StringifyExpr(source=lit(value)).eval(SCOPE) == expected


BLOCKS = [{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {"url": "x"}}]
DEEP_TEXT = '[{"a": ' + "[" * 1_000_000


@parameterized.expand(
    [
        ("a JSON array of content blocks", json.dumps(BLOCKS), BLOCKS),
        ("blocks padded with whitespace", f"\u00a0\n[ {json.dumps(BLOCKS)[1:]}\u2028", BLOCKS),
        ("a block typed after its other keys", '[{"text": "hi", "type": "text"}]', [{"text": "hi", "type": "text"}]),
        ("an empty array", "[]", []),
        ("a plain string", "just text", "just text"),
        ("a non-string", BLOCKS, BLOCKS),
        ("invalid JSON", "[not valid json", "[not valid json"),
        ("blocks of unknown types", '[{"type": "weird"}]', '[{"type": "weird"}]'),
        ("blocks with NaN", '[{"type": "text", "text": "hi", "n": NaN}]', '[{"type": "text", "text": "hi", "n": NaN}]'),
        ("text nested too deeply to parse", DEEP_TEXT, DEEP_TEXT),
    ]
)
def test_try_parse_structured_content(_name: str, value: Value, expected: Value) -> None:
    assert TryParseStructuredContentExpr(source=lit(value)).eval(SCOPE) == expected


@parameterized.expand(
    [
        ("blocks_longer_than_the_cap", json.dumps([{"type": "text", "text": "x" * MAX_PARSE_CHARS}])),
        ("padding_past_the_cap", json.dumps([{"type": "text", "text": "hi"}]) + " " * MAX_PARSE_CHARS),
    ]
)
def test_try_parse_structured_content_keeps_text_longer_than_the_parse_cap_as_text(_name: str, blocks: str) -> None:
    # Checked through a flag, because pytest would otherwise diff two values the size of the parse cap on failure.
    kept_as_text = TryParseStructuredContentExpr(source=lit(blocks)).eval(SCOPE) == blocks
    assert kept_as_text
