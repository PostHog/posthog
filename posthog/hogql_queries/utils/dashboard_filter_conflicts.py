from typing import Any

from posthog.schema import PropertyOperator

_POSITIVE_EXACT_OPERATORS = {PropertyOperator.EXACT, PropertyOperator.IN_}
_NEGATIVE_EXACT_OPERATORS = {PropertyOperator.IS_NOT, PropertyOperator.NOT_IN}
# Operators that can never match an unset (NULL) property value, per _expr_to_compare_op in
# posthog/hogql/property.py. Negated operators (is_not, not_icontains, not_regex) DO match unset
# values there, so they are compatible with is_not_set and must not be listed here.
_MATCHES_ONLY_SET_VALUES = _POSITIVE_EXACT_OPERATORS | {
    PropertyOperator.ICONTAINS,
    PropertyOperator.REGEX,
    PropertyOperator.IS_SET,
}
_INCOMPARABLE_FILTER_TYPES = ("cohort", "hogql")


def filters_contradict(filter_a: Any, filter_b: Any) -> bool:
    """Whether two property filters on the same property provably contradict — ANDing them could never
    match any value (e.g. `utm_medium = abc` vs `utm_medium != abc`, or `= google` vs `= facebook`).

    Compatible pairs like `= google` and `is set` return False so they stack (AND-combine) rather than one
    replacing the other. Anything not provably contradictory is treated as compatible.

    """
    if not _same_property(filter_a, filter_b):
        return False
    op_a, values_a = _operator_and_values(filter_a)
    op_b, values_b = _operator_and_values(filter_b)
    return _contradicts_one_way(op_a, values_a, op_b, values_b) or _contradicts_one_way(op_b, values_b, op_a, values_a)


def _same_property(filter_a: Any, filter_b: Any) -> bool:
    for f in (filter_a, filter_b):
        # A malformed filter list can carry a bare value (e.g. a string) instead of a filter dict; such
        # an entry has no property to compare, so treat it as a different property rather than crashing.
        if not isinstance(f, dict):
            return False
        if f.get("key") is None:
            return False
        if f.get("type") in _INCOMPARABLE_FILTER_TYPES:
            return False
    return (
        filter_a.get("key") == filter_b.get("key")
        and filter_a.get("type") == filter_b.get("type")
        and filter_a.get("group_type_index") == filter_b.get("group_type_index")
    )


def _contradicts_one_way(
    op_a: PropertyOperator, values_a: list[str] | None, op_b: PropertyOperator, values_b: list[str] | None
) -> bool:
    """Is `a` a positively-matching filter that `b` negates entirely?"""
    if op_b == PropertyOperator.IS_NOT_SET and op_a in _MATCHES_ONLY_SET_VALUES:
        # A valueless exact/in/icontains/regex filter is a no-op, so only is_set conflicts unconditionally
        return op_a == PropertyOperator.IS_SET or values_a is not None
    if values_a is None or values_b is None:
        return False
    if op_a in _POSITIVE_EXACT_OPERATORS:
        if op_b in _NEGATIVE_EXACT_OPERATORS:
            return set(values_a) <= set(values_b)
        if op_b in _POSITIVE_EXACT_OPERATORS:
            return not set(values_a) & set(values_b)
    if op_a == PropertyOperator.ICONTAINS and op_b == PropertyOperator.NOT_ICONTAINS:
        # icontains matches values containing ANY needle; not_icontains requires containing NONE.
        # Unsatisfiable when every icontains needle itself contains an excluded needle.
        positive_needles = [v.casefold() for v in values_a]
        negative_needles = [v.casefold() for v in values_b]
        return all(any(negative in positive for negative in negative_needles) for positive in positive_needles)
    if op_a == PropertyOperator.REGEX and op_b == PropertyOperator.NOT_REGEX:
        return len(values_a) == 1 and len(values_b) == 1 and values_a[0] == values_b[0]
    return False


def _operator_and_values(property_filter: dict) -> tuple[PropertyOperator, list[str] | None]:
    operator = property_filter.get("operator") or PropertyOperator.EXACT
    return PropertyOperator(operator), _normalized_values(property_filter.get("value"))


def _normalized_values(value: Any) -> list[str] | None:
    """None for valueless/empty filters (no-ops per posthog/hogql/property.py), else stringified values."""
    if value is None:
        return None
    values = value if isinstance(value, list) else [value]
    if not values:
        return None
    return [_canonicalize_value(v) for v in values]


def _canonicalize_value(value: Any) -> str:
    # JSON booleans and the lowercase strings the UI offers for boolean properties are interchangeable;
    # mixed-case strings like "True" stay untouched since string comparison in ClickHouse is case-sensitive
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
