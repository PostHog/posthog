from abc import ABC, abstractmethod
from typing import Literal

from posthog.dataclasses import frozen

from .run_limits import check_time_limit
from .values import Missing, Value, has_field, is_list, is_mapping, is_number, is_object_like, read_field, strict_equals

type TypeName = Literal["string", "array", "object", "null", "number", "boolean", "any"]


def matches_type(value: Value, type_name: TypeName) -> bool:
    match type_name:
        case "any":
            return True
        case "string":
            return isinstance(value, str)
        case "number":
            return is_number(value)
        case "boolean":
            return isinstance(value, bool)
        case "null":
            return value is None
        case "array":
            return is_list(value)
        case "object":
            return is_mapping(value)


class Predicate(ABC):
    __slots__ = ()

    def test(self, value: Value, present: bool) -> bool:
        # A team recipe can build one pattern that runs for minutes, so every test checks the clock.
        check_time_limit()
        return self._test(value, present)

    @abstractmethod
    def _test(self, value: Value, present: bool) -> bool: ...


@frozen
class Pattern:
    fields: tuple[tuple[str, Predicate], ...]

    def matches(self, value: Value) -> bool:
        for field, predicate in self.fields:
            if field == "$":
                candidate, present = value, not isinstance(value, Missing)
            else:
                candidate, present = read_field(value, field), has_field(value, field)
            if not predicate.test(candidate, present):
                return False
        return True


@frozen
class EqualsPredicate(Predicate):
    expected: Value

    def _test(self, value: Value, present: bool) -> bool:
        return present and strict_equals(value, self.expected)


@frozen
class ExistsPredicate(Predicate):
    should_exist: bool

    def _test(self, value: Value, present: bool) -> bool:
        return present is self.should_exist


@frozen
class IsPredicate(Predicate):
    types: tuple[TypeName, ...]

    def _test(self, value: Value, present: bool) -> bool:
        return present and any(matches_type(value, type_name) for type_name in self.types)


@frozen
class InPredicate(Predicate):
    values: tuple[Value, ...]

    def _test(self, value: Value, present: bool) -> bool:
        if not present:
            return False
        for candidate in self.values:
            # One comparison can scan a whole string, and a recipe can list many long candidates, so the scan checks the
            # clock between comparisons.
            check_time_limit()
            if strict_equals(value, candidate):
                return True
        return False


@frozen
class ShapePredicate(Predicate):
    nested: Pattern

    def _test(self, value: Value, present: bool) -> bool:
        return present and is_object_like(value) and self.nested.matches(value)


@frozen
class EveryPredicate(Predicate):
    element: Predicate

    def _test(self, value: Value, present: bool) -> bool:
        if not present or not is_list(value) or len(value) == 0:
            return False
        return all(self.element.test(item, not isinstance(item, Missing)) for item in value)
