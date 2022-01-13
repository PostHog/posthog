from typing import Any

from constance import config, settings
from rest_framework import request, response, viewsets
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


class InstanceSettingsViewset(viewsets.ViewSet):
    permission_classes = [StaffUser]

    def list(self, request: request.Request) -> response.Response:
        res = {}
        for key, setting_config in settings.CONFIG.items():
            if key in SETTINGS_ALLOWING_API_OVERRIDE:
                res[key] = {"value": getattr(config, key), "description": setting_config[1]}
        return response.Response(res)

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
