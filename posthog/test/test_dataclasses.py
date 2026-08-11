import dataclasses
from functools import cached_property

import pytest

from posthog.dataclasses import frozen


@frozen
class Point:
    x: int
    y: int


@frozen(slots=False)
class WithCache:
    value: int

    @cached_property
    def doubled(self) -> int:
        return self.value * 2


class TestFrozenDefaults:
    def test_construction_is_keyword_only(self):
        point = Point(x=1, y=2)
        assert (point.x, point.y) == (1, 2)
        with pytest.raises(TypeError):
            Point(1, 2)  # type: ignore[misc]

    def test_instances_are_immutable_and_hashable(self):
        point = Point(x=1, y=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            point.x = 3  # type: ignore[misc]  # ty: ignore[invalid-assignment]
        assert point == Point(x=1, y=2)
        assert hash(point) == hash(Point(x=1, y=2))
        assert dataclasses.replace(point, x=3) == Point(x=3, y=2)

    def test_slots_by_default(self):
        assert not hasattr(Point(x=1, y=2), "__dict__")

    def test_flags_can_be_overridden(self):
        instance = WithCache(value=21)
        assert instance.doubled == 42
