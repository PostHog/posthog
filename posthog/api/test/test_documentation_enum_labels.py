from dataclasses import dataclass, field
from typing import Any, cast

from django.test import SimpleTestCase

from drf_spectacular.openapi import AutoSchema
from parameterized import parameterized
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.documentation import LabeledEnumDataclassSerializerExtension, _use_class_labels
from posthog.enums import LabeledStrEnum


class _Kind(LabeledStrEnum):
    OPEN = "open"
    CLOSED_NOW = "closed_now"


@dataclass(frozen=True)
class _Row:
    kind: _Kind
    kinds: list[_Kind] = field(default_factory=list)
    by_name: _Kind = _Kind.OPEN
    custom: _Kind = _Kind.OPEN


class _RowSerializer(DataclassSerializer):
    class Meta:
        dataclass = _Row
        extra_kwargs = {
            "by_name": {"by_name": True},
            "custom": {"choices": [("open", "Only open")]},
        }


class _CapturingAutoSchema:
    def __init__(self) -> None:
        self.mapped: Any = None

    def _map_serializer(self, serializer: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.mapped = serializer
        return {}


def _choices(serializer_field: Any) -> dict[str, str]:
    return dict(getattr(serializer_field, "child", serializer_field).choices)


class TestEnumLabelsExtension(SimpleTestCase):
    @parameterized.expand(
        [
            ("kind", {"open": "Open", "closed_now": "Closed Now"}),
            ("kinds", {"open": "Open", "closed_now": "Closed Now"}),
            ("by_name", {"OPEN": "OPEN", "CLOSED_NOW": "CLOSED_NOW"}),
            ("custom", {"open": "Only open"}),
        ]
    )
    def test_use_class_labels(self, field_name: str, expected: dict[str, str]) -> None:
        serializer_field = _RowSerializer().fields[field_name]
        _use_class_labels(serializer_field)
        assert _choices(serializer_field) == expected

    @parameterized.expand([(True,), (False,)])
    def test_extension_maps_a_copy_and_keeps_partial(self, partial: bool) -> None:
        original = _RowSerializer(partial=partial)
        auto_schema = _CapturingAutoSchema()

        LabeledEnumDataclassSerializerExtension(original).map_serializer(cast(AutoSchema, auto_schema), "response")

        assert auto_schema.mapped is not original
        assert auto_schema.mapped.partial is partial
        assert _choices(auto_schema.mapped.fields["kind"]) == {"open": "Open", "closed_now": "Closed Now"}
        assert _choices(original.fields["kind"]) == {"open": "OPEN", "closed_now": "CLOSED_NOW"}
