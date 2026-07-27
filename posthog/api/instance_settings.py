import re
import json
from typing import Any, Optional, Union, cast, get_args, get_origin

import structlog
from rest_framework import exceptions, mixins, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import (
    get_instance_setting as get_instance_setting_raw,
    set_instance_setting as set_instance_setting_raw,
)
from posthog.permissions import IsStaffUser
from posthog.settings import (
    CONSTANCE_CONFIG,
    SECRET_SETTINGS,
    SETTINGS_ALLOWING_API_OVERRIDE,
    SKIP_ASYNC_MIGRATIONS_SETUP,
)
from posthog.tasks.email import send_canary_email
from posthog.utils import str_to_bool

logger = structlog.get_logger(__name__)

REDACTED = "<redacted>"
UNSET = "<unset>"


def _redact_if_secret(key: str, value: Any) -> Any:
    if key not in SECRET_SETTINGS:
        return value
    if value is None or value == "":
        return UNSET
    return REDACTED


def cast_str_to_desired_type(value: Any, target_type: type) -> Any:
    if target_type is int:
        return int(value)

    if target_type is bool:
        return str_to_bool(value)

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

    def __init__(self, **kwargs):
        for field in (
            "key",
            "value",
            "value_type",
            "description",
            "editable",
            "is_secret",
        ):
            setattr(self, field, kwargs.get(field, None))


def get_instance_setting(key: str, setting_config: Optional[tuple] = None) -> InstanceSettingHelper:
    setting_config = setting_config or CONSTANCE_CONFIG[key]
    is_secret = key in SECRET_SETTINGS
    value = get_instance_setting_raw(key)

    return InstanceSettingHelper(
        key=key,
        value=value if not is_secret or not value else "*****",
        value_type=re.sub(r"<class '(\w+)'>", r"\1", str(setting_config[2])),
        description=setting_config[1],
        editable=key in SETTINGS_ALLOWING_API_OVERRIDE,
        is_secret=is_secret,
    )


class InstanceSettingsSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    value = serializers.JSONField()  # value can be bool, int, or str
    value_type = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    editable = serializers.BooleanField(read_only=True)
    is_secret = serializers.BooleanField(read_only=True)

    def update(self, instance: InstanceSettingHelper, validated_data: dict[str, Any]) -> InstanceSettingHelper:
        if instance.key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError("This setting cannot be updated from the API.", code="no_api_override")

        if validated_data["value"] is None:
            raise serializers.ValidationError({"value": "This field is required."}, code="required")

        request = self.context.get("request")

        before_value = get_instance_setting_raw(instance.key)

        target_type: type = CONSTANCE_CONFIG[instance.key][2]
        if target_type is bool and isinstance(validated_data["value"], bool):
            new_value_parsed = validated_data["value"]
        else:
            try:
                new_value_parsed = cast_str_to_desired_type(validated_data["value"], target_type)
            except (ValueError, TypeError) as e:
                raise serializers.ValidationError({"value": str(e)})

        if instance.key == "RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS":
            if is_cloud():
                # On cloud the TTL is set on the performance_events_sharded table,
                # so this command should never be run
                raise serializers.ValidationError("This setting cannot be updated on cloud.")

            # TODO: Move to top-level imports once CH is moved out of `ee`
            from posthog.clickhouse.client import sync_execute
            from posthog.models.performance.sql import UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL

            sync_execute(UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL(), {"weeks": new_value_parsed})

        set_instance_setting_raw(instance.key, new_value_parsed)
        instance.value = new_value_parsed

        if request is not None:
            self._log_setting_change(request, instance.key, before_value, new_value_parsed)

            if instance.key.startswith("EMAIL_"):
                # Partial EMAIL_* updates (e.g. setting EMAIL_HOST_PASSWORD before EMAIL_HOST)
                # would otherwise raise ImproperlyConfigured and fail the request with a 500.
                if is_email_available(with_absolute_urls=True):
                    send_canary_email.apply_async(kwargs={"user_email": request.user.email})

        if instance.key.startswith("ASYNC_MIGRATION") and not SKIP_ASYNC_MIGRATIONS_SETUP:
            from posthog.async_migrations.setup import setup_async_migrations

            setup_async_migrations()

        return instance

    def _log_setting_change(self, request: Request, key: str, before_value: Any, new_value: Any) -> None:
        if before_value == new_value:
            return

        # IsAuthenticated + IsStaffUser permission classes guarantee this is a real User.
        user = cast(User, request.user)
        organization = user.organization
        if organization is None:
            logger.warning(
                "instance_settings_audit_log_skipped_no_organization",
                user_id=user.id,
                key=key,
            )
            return

        log_activity(
            organization_id=organization.id,
            team_id=None,
            user=user,
            was_impersonated=is_impersonated(request),
            item_id=key,
            scope="InstanceSetting",
            activity="updated",
            detail=Detail(
                name=key,
                changes=[
                    Change(
                        type="InstanceSetting",
                        field=key,
                        action="changed",
                        before=_redact_if_secret(key, before_value),
                        after=_redact_if_secret(key, new_value),
                    )
                ],
            ),
        )


class InstanceSettingsViewset(
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
):
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]
    serializer_class = InstanceSettingsSerializer
    lookup_field = "key"

    def get_queryset(self):
        output = []
        for key, setting_config in CONSTANCE_CONFIG.items():
            output.append(get_instance_setting(key, setting_config))
        return output

    def get_object(self) -> InstanceSettingHelper:
        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        key = self.kwargs[lookup_url_kwarg]

        if key not in CONSTANCE_CONFIG:
            raise exceptions.NotFound(f"Setting with key `{key}` does not exist.")

        return get_instance_setting(key)
