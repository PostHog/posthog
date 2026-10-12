from typing import Any
from uuid import uuid4

from rest_framework import serializers
from rest_framework.fields import empty


class ConditionSetSerializer(serializers.Serializer):
    """Base for a stored condition set: {id, rollout_percentage, properties}.

    DRF reads `partial` from the root serializer, so on a PATCH a nested set skips its required
    checks and defaults. Fill them here, or the stored set misses keys and every later read fails.
    """

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict) and not data.get("id"):
            data = {**data, "id": str(uuid4())}
        attrs = super().to_internal_value(data)
        for field in self.fields.values():
            if field.source not in attrs and field.default is not empty:
                attrs[field.source] = field.default() if callable(field.default) else field.default
        return attrs

    def to_representation(self, instance: Any) -> dict[str, Any]:
        # Rows written before the write path filled the id must stay readable. Saving the set
        # back through the API stores the id this read returns.
        if isinstance(instance, dict) and not instance.get("id"):
            instance = {**instance, "id": str(uuid4())}
        return super().to_representation(instance)
