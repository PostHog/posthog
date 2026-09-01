from collections.abc import Mapping
from typing import cast

from rest_framework import serializers


class StrictDatasetSerializer(serializers.Serializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, Mapping):
            unknown_fields = sorted(set(data) - set(self.fields))
            if unknown_fields:
                raise serializers.ValidationError({field: ["This field is not supported."] for field in unknown_fields})
        return cast(dict[str, object], super().to_internal_value(data))
