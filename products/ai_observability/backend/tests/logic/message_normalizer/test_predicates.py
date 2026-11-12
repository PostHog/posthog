from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.predicates import (
    EqualsPredicate,
    EveryPredicate,
    ExistsPredicate,
    InPredicate,
    IsPredicate,
    Pattern,
    Predicate,
    ShapePredicate,
    TypeName,
    matches_type,
)
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, Value

ALL_STRINGS = EveryPredicate(element=IsPredicate(types=("string",)))
TEXT_SHAPE = ShapePredicate(nested=Pattern(fields=(("type", EqualsPredicate(expected="text")),)))


@parameterized.expand(
    [
        ("equals a present match", EqualsPredicate(expected="tool"), "tool", True, True),
        ("equals a mismatch", EqualsPredicate(expected="tool"), "other", True, False),
        ("equals an absent field", EqualsPredicate(expected=MISSING), MISSING, False, False),
        ("equals 1 never matches true", EqualsPredicate(expected=1), True, True, False),
        ("equals 0 never matches false", EqualsPredicate(expected=0), False, True, False),
        ("exists when expected", ExistsPredicate(should_exist=True), "any", True, True),
        ("exists false on an absent field", ExistsPredicate(should_exist=False), MISSING, False, True),
        ("exists on an absent field", ExistsPredicate(should_exist=True), MISSING, False, False),
        ("exists false on a present field", ExistsPredicate(should_exist=False), "any", True, False),
        ("in a member", InPredicate(values=("a", "b", "c")), "b", True, True),
        ("in a non-member", InPredicate(values=("a", "b")), "z", True, False),
        ("in an absent field", InPredicate(values=("a", "b")), MISSING, False, False),
        ("in numbers never matches true", InPredicate(values=(0, 1)), True, True, False),
        ("in numbers never matches false", InPredicate(values=(0, 1)), False, True, False),
        ("is a listed string", IsPredicate(types=("string", "array")), "hi", True, True),
        ("is a listed array", IsPredicate(types=("string", "array")), [1], True, True),
        ("is an unlisted type", IsPredicate(types=("string",)), 42, True, False),
        ("is an absent field", IsPredicate(types=("string",)), MISSING, False, False),
        ("is number rejects a boolean", IsPredicate(types=("number",)), True, True, False),
        ("every element matches", ALL_STRINGS, ["a", "b", "c"], True, True),
        ("every with one failing element", ALL_STRINGS, ["a", 2, "c"], True, False),
        ("every on an empty list", ALL_STRINGS, [], True, False),
        ("every on a non-list", ALL_STRINGS, "not an array", True, False),
        ("shape on a matching object", TEXT_SHAPE, {"type": "text", "text": "hi"}, True, True),
        ("shape on a mismatching object", TEXT_SHAPE, {"type": "image"}, True, False),
        ("shape on a string", TEXT_SHAPE, "text", True, False),
        ("shape on null", TEXT_SHAPE, None, True, False),
        ("shape on an absent field", TEXT_SHAPE, MISSING, False, False),
        ("shape accepts a list as JavaScript does", ShapePredicate(nested=Pattern(fields=())), [1], True, True),
    ]
)
def test_predicate(_name: str, predicate: Predicate, value: Value, present: bool, expected: bool) -> None:
    assert predicate.test(value, present) is expected


@parameterized.expand(
    [
        ("string", "hi", True),
        ("number", 42, True),
        ("number", 1.5, True),
        ("boolean", True, True),
        ("null", None, True),
        ("array", [1, 2], True),
        ("object", {"a": 1}, True),
        ("any", "hi", True),
        ("any", None, True),
        ("any", [1], True),
        ("object", [1, 2], False),
        ("object", None, False),
        ("number", False, False),
        ("string", MISSING, False),
    ]
)
def test_matches_type(type_name: TypeName, value: Value, expected: bool) -> None:
    assert matches_type(value, type_name) is expected


PATTERN = Pattern(fields=(("role", EqualsPredicate(expected="user")), ("content", IsPredicate(types=("string",)))))


@parameterized.expand(
    [
        ("every field passes", PATTERN, {"role": "user", "content": "hi"}, True),
        ("one field fails", PATTERN, {"role": "user", "content": 42}, False),
        ("$ matches the whole value", Pattern(fields=(("$", IsPredicate(types=("string",))),)), "a bare string", True),
        ("$ rejects the whole value", Pattern(fields=(("$", IsPredicate(types=("string",))),)), {"a": 1}, False),
        (
            "an absent field is not present",
            Pattern(fields=(("role", ExistsPredicate(should_exist=False)),)),
            {"content": "hi"},
            True,
        ),
        (
            "a present field is present",
            Pattern(fields=(("role", ExistsPredicate(should_exist=False)),)),
            {"role": "user"},
            False,
        ),
    ]
)
def test_pattern_matches(_name: str, pattern: Pattern, value: Value, expected: bool) -> None:
    assert pattern.matches(value) is expected
