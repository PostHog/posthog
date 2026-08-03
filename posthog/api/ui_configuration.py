import json
from typing import Any, Optional

import pydantic
from rest_framework import serializers

from posthog.schema import UserUIConfiguration

# Far above any legitimate configuration (a fully customized sidebar is ~2 KB), but low enough
# that the blob can't be abused as arbitrary storage served on every /api/users/@me and team read.
UI_CONFIGURATION_MAX_BYTES = 65536


def validate_ui_configuration_value(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Shared validation for `User.ui_configuration` and `Team.default_ui_configuration` payloads."""
    if value is None:
        return None
    if len(json.dumps(value, separators=(",", ":"))) > UI_CONFIGURATION_MAX_BYTES:
        raise serializers.ValidationError(
            f"UI configuration is too large (max {UI_CONFIGURATION_MAX_BYTES} bytes).", code="invalid_input"
        )
    try:
        UserUIConfiguration.model_validate(value)
    except pydantic.ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'root'}: {error['msg']}" for error in e.errors()
        )
        raise serializers.ValidationError(
            f"Does not match the UserUIConfiguration schema: {errors}", code="invalid_input"
        )
    return value
