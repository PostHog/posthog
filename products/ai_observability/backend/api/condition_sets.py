from typing import Any
from uuid import uuid4

from rest_framework import serializers


class ConditionSetSerializer(serializers.Serializer):
    """Base for a stored condition set: {id, rollout_percentage, properties}.

    DRF reads `partial` from the root serializer, so on a PATCH a nested set skips its required
    `id` check. Generate a missing id here, or the stored set has no id and every later read fails.
    """

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict) and not data.get("id"):
            data = {**data, "id": str(uuid4())}
        return super().to_internal_value(data)
