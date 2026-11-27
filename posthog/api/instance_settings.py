import re
import json
from typing import Any, Optional, Union, cast, get_args, get_origin

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import (
    InstanceSetting,
    get_instance_setting as get_instance_setting_raw,
    set_instance_setting as set_instance_setting_raw,
)
from posthog.permissions import IsStaffUser
from posthog.settings import (
    CONSTANCE_CONFIG,
    CONSTANCE_DATABASE_PREFIX,
    SECRET_SETTINGS,
    SETTINGS_ALLOWING_API_OVERRIDE,
)
from posthog.utils import str_to_bool

logger = structlog.get_logger(__name__)

RAW_VALUE_MAX_LENGTH = cast(int, InstanceSetting._meta.get_field("raw_value").max_length)


def _parse_for_storage(key: str, value: Any) -> Any:
    target_type: type = CONSTANCE_CONFIG[key][2]
    if target_type is bool:
        return value if isinstance(value, bool) else str_to_bool(value)
    if target_type is int:
        return int(value)
    if get_origin(target_type) is list:
        return _parse_list_value(value, target_type)
    return value


def _parse_list_value(value: Any, target_type: type) -> list:
    args = get_args(target_type)
    item_type: type = args[0] if args else str

    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON array: {e}") from e
            if not isinstance(parsed, list):
                raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")
            items = parsed
        else:
            items = [v.strip() for v in stripped.split(",") if v.strip()]
    else:
        raise ValueError(f"Cannot convert {type(value).__name__!r} to {target_type}")

    try:
        return [item_type(item) for item in items]
    except (ValueError, TypeError) as e:
        raise ValueError(f"All items must be of type {item_type.__name__}: {e}") from e


class InstanceSettingHelper:
    key: str = ""
    value: Union[str, bool, int, None] = None
    value_type: str = ""
    description: str = ""
    editable: bool = False
    is_secret: bool = False
    is_set_in_database: bool = False

    def __init__(self, **kwargs):
        for field in (
            "key",
            "value",
            "value_type",
            "description",
            "editable",
            "is_secret",
            "is_set_in_database",
        ):
            setattr(self, field, kwargs.get(field, None))


def _keys_set_in_database() -> set[str]:
    return {
        key.removeprefix(CONSTANCE_DATABASE_PREFIX)
        for key in InstanceSetting.objects.filter(key__startswith=CONSTANCE_DATABASE_PREFIX).values_list(
            "key", flat=True
        )
    }


def get_instance_setting(
    key: str, setting_config: Optional[tuple] = None, keys_set_in_database: Optional[set[str]] = None
) -> InstanceSettingHelper:
    setting_config = setting_config or CONSTANCE_CONFIG[key]
    is_secret = key in SECRET_SETTINGS
    value = get_instance_setting_raw(key)
    if keys_set_in_database is None:
        keys_set_in_database = _keys_set_in_database()

    return InstanceSettingHelper(
        key=key,
        value=value if not is_secret or not value else "*****",
        value_type=re.sub(r"<class '(\w+)'>", r"\1", str(setting_config[2])),
        description=setting_config[1],
        editable=key in SETTINGS_ALLOWING_API_OVERRIDE,
        is_secret=is_secret,
        is_set_in_database=key in keys_set_in_database,
    )


class InstanceSettingsSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True, help_text="Name of the setting and of its environment variable.")
    value = serializers.JSONField(help_text="Value in effect. Secret values are masked.")
    value_type = serializers.CharField(read_only=True, help_text="Python type of the value.")
    description = serializers.CharField(read_only=True, help_text="What the setting controls.")
    editable = serializers.BooleanField(
        read_only=True, help_text="Whether staff can still change this setting from PostHog."
    )
    is_secret = serializers.BooleanField(
        read_only=True, help_text="Whether the value is a credential and never returned."
    )
    is_set_in_database = serializers.BooleanField(
        read_only=True,
        help_text="Whether a deprecated database value overrides the environment variable for this setting.",
    )

    def validate_value(self, value: Any) -> Any:
        if self.instance is None or self.instance.key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError(
                "This setting can only be changed with its environment variable.", code="no_api_override"
            )
        if value is None:
            raise serializers.ValidationError("This field is required.", code="required")
        if self.instance.key == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS":
            # Every query parses this list, so a value that fails to parse would fail every query on the instance.
            if not isinstance(value, str) or not re.fullmatch(r"\s*(\d+\s*(,\s*\d+\s*)*)?", value):
                raise serializers.ValidationError(
                    "Enter project IDs separated by commas, or leave it empty to switch no project."
                )
        try:
            stored_value = _parse_for_storage(self.instance.key, value)
        except (ValueError, TypeError) as e:
            raise serializers.ValidationError(str(e))
        if len(json.dumps(stored_value)) > RAW_VALUE_MAX_LENGTH:
            raise serializers.ValidationError(
                f"This value is too long. Stored values can be at most {RAW_VALUE_MAX_LENGTH} characters."
            )
        return stored_value

    def update(self, instance: InstanceSettingHelper, validated_data: dict[str, Any]) -> InstanceSettingHelper:
        before_value = get_instance_setting_raw(instance.key)
        new_value = validated_data["value"]

        set_instance_setting_raw(instance.key, new_value)
        instance.value = new_value
        instance.is_set_in_database = True

        request = self.context.get("request")
        if request is not None and before_value != new_value:
            _log_setting_activity(
                request,
                key=instance.key,
                activity="updated",
                changes=[
                    Change(
                        type="InstanceSetting",
                        field=instance.key,
                        action="changed",
                        before=before_value,
                        after=new_value,
                    )
                ],
            )
        return instance


def _log_setting_activity(request: Request, *, key: str, activity: str, changes: list[Change]) -> None:
    # IsAuthenticated + IsStaffUser permission classes guarantee this is a real User.
    user = cast(User, request.user)
    organization = user.organization
    if organization is None:
        logger.warning("instance_settings_audit_log_skipped_no_organization", user_id=user.id, key=key)
        return

    log_activity(
        organization_id=organization.id,
        team_id=None,
        user=user,
        was_impersonated=is_impersonated(request),
        item_id=key,
        scope="InstanceSetting",
        activity=activity,
        detail=Detail(name=key, changes=changes),
    )


class InstanceSettingsViewset(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.UpdateModelMixin):
    """Deprecated. Lists settings, updates the few in SETTINGS_ALLOWING_API_OVERRIDE, and deletes stored values."""

    permission_classes = [permissions.IsAuthenticated, IsStaffUser]
    serializer_class = InstanceSettingsSerializer
    lookup_field = "key"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        keys_set_in_database = _keys_set_in_database()
        return [
            get_instance_setting(key, setting_config, keys_set_in_database)
            for key, setting_config in CONSTANCE_CONFIG.items()
        ]

    def get_object(self) -> InstanceSettingHelper:
        key = self.kwargs[self.lookup_url_kwarg or self.lookup_field]
        if key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError(
                {"value": "This setting can only be changed with its environment variable."}, code="no_api_override"
            )
        return get_instance_setting(key)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        key = self.kwargs[self.lookup_url_kwarg or self.lookup_field]
        if key not in CONSTANCE_CONFIG:
            raise exceptions.NotFound(f"Setting with key `{key}` does not exist.")

        deleted, _ = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).delete()
        if not deleted:
            raise exceptions.NotFound(f"No value is stored for `{key}`.")
        get_instance_setting_raw.cache_clear()  # type: ignore[attr-defined]

        # No before value, so a deleted secret never reaches the activity log.
        _log_setting_activity(request, key=key, activity="deleted", changes=[])
        return Response(status=status.HTTP_204_NO_CONTENT)
