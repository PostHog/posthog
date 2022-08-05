import re
from typing import Any, Dict, Optional, Tuple, Union

from rest_framework import exceptions, mixins, permissions, serializers, viewsets

from posthog.models.instance_setting import get_instance_setting as get_instance_setting_raw
from posthog.models.instance_setting import set_instance_setting as set_instance_setting_raw
from posthog.permissions import IsStaffUser
from posthog.settings import (
    CONSTANCE_CONFIG,
    MULTI_TENANCY,
    SECRET_SETTINGS,
    SETTINGS_ALLOWING_API_OVERRIDE,
    SKIP_ASYNC_MIGRATIONS_SETUP,
)
from posthog.utils import str_to_bool


def cast_str_to_desired_type(str_value: str, target_type: type) -> Any:
    if target_type == int:
        return int(str_value)

    if target_type == bool:
        return str_to_bool(str_value)

    return str_value


class InstanceSettingHelper(object):
    key: str = ""
    value: Union[str, bool, int, None] = None
    value_type: str = ""
    description: str = ""
    editable: bool = False
    is_secret: bool = False

    def __init__(self, **kwargs):
        for field in ("key", "value", "value_type", "description", "editable", "is_secret"):
            setattr(self, field, kwargs.get(field, None))


def get_instance_setting(key: str, setting_config: Optional[Tuple] = None) -> InstanceSettingHelper:
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

    def update(self, instance: InstanceSettingHelper, validated_data: Dict[str, Any]) -> InstanceSettingHelper:
        if instance.key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError("This setting cannot be updated from the API.", code="no_api_override")

        if validated_data["value"] is None:
            raise serializers.ValidationError({"value": "This field is required."}, code="required")

        target_type: type = CONSTANCE_CONFIG[instance.key][2]
        if target_type == bool and isinstance(validated_data["value"], bool):
            new_value_parsed = validated_data["value"]
        else:
            new_value_parsed = cast_str_to_desired_type(validated_data["value"], target_type)

        if instance.key == "RECORDINGS_TTL_WEEKS":

            if MULTI_TENANCY:
                # On cloud the TTL is set on the session_recording_events_sharded table,
                # so this command should never be run
                raise serializers.ValidationError("This setting cannot be updated on MULTI_TENANCY.")

            # TODO: Move to top-level imports once CH is moved out of `ee`
            from posthog.client import sync_execute
            from posthog.models.session_recording_event.sql import UPDATE_RECORDINGS_TABLE_TTL_SQL

            sync_execute(UPDATE_RECORDINGS_TABLE_TTL_SQL(), {"weeks": new_value_parsed})

        set_instance_setting_raw(instance.key, new_value_parsed)
        instance.value = new_value_parsed

        if instance.key.startswith("EMAIL_") and "request" in self.context:
            from posthog.tasks.email import send_canary_email

            send_canary_email.apply_async(kwargs={"user_email": self.context["request"].user.email})
        elif instance.key.startswith("ASYNC_MIGRATION"):
            from posthog.async_migrations.setup import setup_async_migrations

            if not SKIP_ASYNC_MIGRATIONS_SETUP:
                setup_async_migrations()

        return instance


class InstanceSettingsViewset(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin
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
