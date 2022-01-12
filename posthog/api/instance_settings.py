import re
from typing import Any, List, Union

from constance import config, settings
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.permissions import StaffUser
from posthog.settings import SETTINGS_ALLOWING_API_OVERRIDE
from posthog.utils import str_to_bool


def cast_str_to_desired_type(str_value: str, target_type: type) -> Any:
    if target_type == int:
        return int(str_value)

    if target_type == bool:
        return str_to_bool(str_value)

    return str_value


class InstanceSettings(object):
    key: str = ""
    value: Union[str, bool, int, None] = None
    value_type: str = ""
    description: str = ""
    editable: bool = False

    def __init__(self, **kwargs):
        for field in ("key", "value", "value_type", "description", "editable"):
            setattr(self, field, kwargs.get(field, None))


class InstanceSettingsSerializer(serializers.Serializer):
    key = serializers.CharField()
    value = serializers.JSONField()  # value can be bool, int, or str
    value_type = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    editable = serializers.BooleanField()


class InstanceSettingsViewset(viewsets.GenericViewSet, mixins.ListModelMixin):
    permission_classes = [StaffUser]
    serializer_class = InstanceSettingsSerializer

    def get_queryset(self) -> List[InstanceSettings]:
        output = []
        for key, setting_config in settings.CONFIG.items():
            output.append(
                InstanceSettings(
                    key=key,
                    value=getattr(config, key),
                    value_type=re.sub(r"<class '(\w+)'>", r"\1", str(setting_config[2])),
                    description=setting_config[1],
                    editable=key in SETTINGS_ALLOWING_API_OVERRIDE,
                )
            )
        return output

    # Used to capture internal metrics shown on dashboards
    @action(methods=["POST"], detail=False)
    def update_setting(self, request: request.Request) -> response.Response:
        setting_key = request.data["key"]
        new_value = request.data["value"]

        if setting_key not in settings.CONFIG:
            return response.Response({"error": "Setting does not exist."})

        if setting_key in SETTINGS_ALLOWING_API_OVERRIDE:
            target_type = settings.CONFIG[setting_key][2]
            new_value_parsed = cast_str_to_desired_type(new_value, target_type)
            setattr(config, setting_key, new_value_parsed)
            return response.Response({"status": 1})
        else:
            return response.Response({"error": "Setting cannot be updated via the API."})
