from collections.abc import Sequence
from typing import Any

from posthog.schema import DashboardFilterConflict, PropertyOperator

from posthog.types import AnyPropertyFilter

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


def drop_conflicting_insight_filters(
    insight_properties: Sequence[AnyPropertyFilter],
    dashboard_properties: Sequence[AnyPropertyFilter],
) -> tuple[list[AnyPropertyFilter], list[DashboardFilterConflict]]:
    """Drop insight filters that a dashboard filter on the same property provably contradicts.

    A contradiction means ANDing the two filters could never match any value, e.g.
    `utm_medium = abc` vs `utm_medium != abc`. Dashboard filters win: the insight filter is
    dropped and the pair recorded. Anything not provably contradictory is kept (and stacked
    by the caller as usual). Surviving filters are the original instances, not copies.
    """
    surviving: list[AnyPropertyFilter] = []
    conflicts: list[DashboardFilterConflict] = []
    for insight_filter in insight_properties:
        contradicting = next((d for d in dashboard_properties if _contradicts(insight_filter, d)), None)
        if contradicting is None:
            surviving.append(insight_filter)
        else:
            conflicts.append(DashboardFilterConflict(insight_filter=insight_filter, dashboard_filter=contradicting))
    return surviving, conflicts


def _contradicts(filter_a: AnyPropertyFilter, filter_b: AnyPropertyFilter) -> bool:
    if not _same_property(filter_a, filter_b):
        return False
    op_a, values_a = _operator_and_values(filter_a)
    op_b, values_b = _operator_and_values(filter_b)
    return _contradicts_one_way(op_a, values_a, op_b, values_b) or _contradicts_one_way(op_b, values_b, op_a, values_a)


def _same_property(filter_a: AnyPropertyFilter, filter_b: AnyPropertyFilter) -> bool:
    for f in (filter_a, filter_b):
        if getattr(f, "key", None) is None or not hasattr(f, "operator"):
            return False
        if getattr(f, "type", None) in _INCOMPARABLE_FILTER_TYPES:
            return False
    return (
        filter_a.key == filter_b.key  # type: ignore[union-attr]
        and getattr(filter_a, "type", None) == getattr(filter_b, "type", None)
        and getattr(filter_a, "group_type_index", None) == getattr(filter_b, "group_type_index", None)
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


def _operator_and_values(property_filter: AnyPropertyFilter) -> tuple[PropertyOperator, list[str] | None]:
    operator = getattr(property_filter, "operator", None) or PropertyOperator.EXACT
    return operator, _normalized_values(getattr(property_filter, "value", None))


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
