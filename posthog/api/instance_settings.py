from constance import config, settings
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.permissions import StaffUser
from posthog.settings import SETTINGS_ALLOWING_API_OVERRIDE


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
            setattr(config, setting_key, new_value)
            return response.Response({"status": 1})
        else:
            return response.Response({"error": "Setting cannot be updated via the API."})
