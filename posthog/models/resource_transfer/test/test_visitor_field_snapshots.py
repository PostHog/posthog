from __future__ import annotations

from typing import Any, get_args

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.resource_transfer.types import ResourceKind
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


def _classify_fields(visitor: type[ResourceTransferVisitor]) -> dict[str, Any]:
    model = visitor.get_model()
    primitives: list[str] = []
    relations: list[str] = []
    skipped: list[str] = []

    for attr_name in sorted(model.__dict__.keys()):
        if not visitor.should_touch_field(attr_name):
            skipped.append(attr_name)
            continue
        if visitor.is_relation(attr_name):
            relations.append(attr_name)
        else:
            primitives.append(attr_name)

    return {
        "primitive_fields": sorted(primitives),
        "relation_fields": sorted(relations),
        "excluded_fields": sorted(visitor.excluded_fields),
        "skipped_fields": sorted(skipped),
    }


def _get_mutable_visitors() -> list[tuple[str, type[ResourceTransferVisitor]]]:
    visitors: list[tuple[str, type[ResourceTransferVisitor]]] = []
    for kind in get_args(ResourceKind):
        visitor = ResourceTransferVisitor.get_visitor(kind)
        if visitor is not None and not visitor.is_immutable():
            visitors.append((kind, visitor))
    return sorted(visitors, key=lambda pair: pair[0])


MUTABLE_VISITORS = _get_mutable_visitors()


@pytest.mark.usefixtures("unittest_snapshot")
class TestVisitorFieldSnapshots(BaseTest):
    snapshot: Any

    @parameterized.expand(MUTABLE_VISITORS, name_func=lambda fn, _, params: f"{fn.__name__}_{params[0][0]}")
    def test_primitive_fields(self, _name: str, visitor: type[ResourceTransferVisitor]) -> None:
        classification = _classify_fields(visitor)
        assert classification["primitive_fields"] == self.snapshot

    @parameterized.expand(MUTABLE_VISITORS, name_func=lambda fn, _, params: f"{fn.__name__}_{params[0][0]}")
    def test_relation_fields(self, _name: str, visitor: type[ResourceTransferVisitor]) -> None:
        classification = _classify_fields(visitor)
        assert classification["relation_fields"] == self.snapshot

    @parameterized.expand(MUTABLE_VISITORS, name_func=lambda fn, _, params: f"{fn.__name__}_{params[0][0]}")
    def test_excluded_fields(self, _name: str, visitor: type[ResourceTransferVisitor]) -> None:
        classification = _classify_fields(visitor)
        assert classification["excluded_fields"] == self.snapshot

    @parameterized.expand(MUTABLE_VISITORS, name_func=lambda fn, _, params: f"{fn.__name__}_{params[0][0]}")
    def test_skipped_fields(self, _name: str, visitor: type[ResourceTransferVisitor]) -> None:
        classification = _classify_fields(visitor)
        assert classification["skipped_fields"] == self.snapshot
