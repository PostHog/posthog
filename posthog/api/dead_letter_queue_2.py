import re
from typing import Any, Dict, List, Optional, Union

from constance import config, settings
from rest_framework import exceptions, mixins, permissions, serializers, viewsets

from posthog.permissions import IsStaffUser
from posthog.settings import SETTINGS_ALLOWING_API_OVERRIDE




class DeadLetterQueueMetric(object):
    key: str = ""
    metric: str = ""
    value: Union[str, bool, int, None] = None
    subrows: Optional[List[Any]] = None

    def __init__(self, **kwargs):
        for field in ("key", "value", "value", "subrows"):
            setattr(self, field, kwargs.get(field, None))


def get_dlq_metric(key: str, setting_config: Dict = {}) -> DeadLetterQueueMetric:

    

    return InstanceSetting(
        key=key,
        value=getattr(config, key),
        value_type=re.sub(r"<class '(\w+)'>", r"\1", str(setting_config[2])),
        description=setting_config[1],
        editable=key in SETTINGS_ALLOWING_API_OVERRIDE,
    )


class InstanceSettingsSerializer(serializers.Serializer):
    key = serializers.CharField()
    value = serializers.JSONField()  # value can be bool, int, or str
    value_type = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    editable = serializers.BooleanField()

    def update(self, instance: InstanceSetting, validated_data: Dict[str, Any]) -> InstanceSetting:
        if instance.key not in SETTINGS_ALLOWING_API_OVERRIDE:
            raise serializers.ValidationError("This setting cannot be updated from the API.", code="no_api_override")
        if validated_data["value"]:
            target_type = settings.CONFIG[instance.key][2]
            new_value_parsed = cast_str_to_desired_type(validated_data["value"], target_type)
            setattr(config, instance.key, new_value_parsed)
            instance.value = new_value_parsed
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
