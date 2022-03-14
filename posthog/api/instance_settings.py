import re
from typing import Any, Dict, Union

from constance import config, settings
from rest_framework import exceptions, mixins, permissions, serializers, viewsets

from posthog.permissions import IsStaffUser
from posthog.settings import MULTI_TENANCY, SETTINGS_ALLOWING_API_OVERRIDE
from posthog.utils import str_to_bool


def cast_str_to_desired_type(str_value: str, target_type: type) -> Any:
    if target_type == int:
        return int(str_value)

    if target_type == bool:
        return str_to_bool(str_value)

    return str_value


class InstanceSetting(object):
    key: str = ""
    value: Union[str, bool, int, None] = None
    value_type: str = ""
    description: str = ""
    editable: bool = False

    def __init__(self, **kwargs):
        for field in ("key", "value", "value_type", "description", "editable"):
            setattr(self, field, kwargs.get(field, None))


def get_instance_setting(key: str, setting_config: Dict = {}) -> InstanceSetting:

    if setting_config == {}:
        for _key, setting_config in settings.CONFIG.items():
            if _key == key:
                break

    return InstanceSetting(
        key=key,
        value=getattr(config, key),
        value_type=re.sub(r"<class '(\w+)'>", r"\1", str(setting_config[2])),
        description=setting_config[1],
        editable=key in SETTINGS_ALLOWING_API_OVERRIDE,
    )


class InstanceSettingsSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    value = serializers.JSONField()  # value can be bool, int, or str
    value_type = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    editable = serializers.BooleanField(read_only=True)

    def update(self, instance: InstanceSetting, validated_data: Dict[str, Any]) -> InstanceSetting:
        if instance.key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError("This setting cannot be updated from the API.", code="no_api_override")

        if validated_data["value"] is None:
            raise serializers.ValidationError({"value": "This field is required."}, code="required")

        target_type = settings.CONFIG[instance.key][2]
        if target_type == "bool" and isinstance(validated_data["value"], bool):
            new_value_parsed = validated_data["value"]
        else:
            new_value_parsed = cast_str_to_desired_type(validated_data["value"], target_type)

        if instance.key == "RECORDINGS_TTL_WEEKS":

            if MULTI_TENANCY:
                # On cloud the TTL is set on the session_recording_events_sharded table,
                # so this command should never be run
                raise serializers.ValidationError("This setting cannot be updated on MULTI_TENANCY.")

            # TODO: Move to top-level imports once CH is moved out of `ee`
            from ee.clickhouse.client import sync_execute
            from ee.clickhouse.sql.session_recording_events import UPDATE_RECORDINGS_TABLE_TTL_SQL

            sync_execute(UPDATE_RECORDINGS_TABLE_TTL_SQL(), {"weeks": new_value_parsed})

        setattr(config, instance.key, new_value_parsed)
        instance.value = new_value_parsed

        if instance.key.startswith("EMAIL_") and "request" in self.context:
            from posthog.tasks.email import send_canary_email

            send_canary_email.apply_async(kwargs={"user_email": self.context["request"].user.email})

        return instance


class InstanceSettingsViewset(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin
):
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]
    serializer_class = InstanceSettingsSerializer
    lookup_field = "key"

    def get_queryset(self):
        output = []
        for key, setting_config in settings.CONFIG.items():
            output.append(get_instance_setting(key, setting_config))
        return output

    def get_object(self) -> InstanceSetting:
        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        key = self.kwargs[lookup_url_kwarg]

        if key not in settings.CONFIG:
            raise exceptions.NotFound(f"Setting with key `{key}` does not exist.")

        return get_instance_setting(key)
