from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

from django.http import QueryDict

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


def validate_query_parameters(data: object, supported: Iterable[str]) -> None:
    if isinstance(data, Mapping):
        unsupported = set(data) - set(supported)
        if unsupported:
            raise serializers.ValidationError({str(name): ["This parameter is not supported."] for name in unsupported})
    if isinstance(data, QueryDict):
        repeated = {key: ["Supply this parameter once."] for key in data if len(data.getlist(key)) != 1}
        if repeated:
            raise serializers.ValidationError(repeated)


class StrictQuerySerializer(serializers.Serializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        validate_query_parameters(data, self.fields)
        return super().to_internal_value(cast(dict[str, object], data))


class EmptyQuerySerializer(StrictQuerySerializer):
    pass


class EmptyQuerySerializerExtension(OpenApiSerializerExtension):
    target_class = EmptyQuerySerializer

    def map_serializer(self, auto_schema: "AutoSchema", direction: "Direction") -> dict[str, object]:
        # drf-spectacular requires properties when expanding query serializers, even when there are no fields.
        return {"type": "object", "properties": {}}
