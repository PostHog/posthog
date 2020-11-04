import json
import os
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields import JSONField
from django.utils.timezone import now
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.models.plugin import Plugin, PluginConfig
from posthog.plugins import (
    can_configure_plugins_via_api,
    can_install_plugins_via_api,
    download_plugin_github_zip,
    reload_plugins_on_workers,
)
from posthog.plugins.utils import load_json_file
from posthog.redis import get_client


class PluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plugin
        fields = ["id", "name", "description", "url", "config_schema", "tag", "error", "from_json"]
        read_only_fields = ["id", "error", "from_json"]

    def get_error(self, plugin: Plugin) -> Optional[JSONField]:
        if plugin.error and can_install_plugins_via_api():
            return plugin.error
        return None

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        if not can_install_plugins_via_api():
            raise ValidationError("Plugin installation via the web is disabled!")

        local_plugin = validated_data.get("url", "").startswith("file:")

        if local_plugin:
            plugin_path = validated_data["url"][5:]
            json_path = os.path.join(plugin_path, "plugin.json")
            json = load_json_file(json_path)
            if not json:
                raise ValidationError("Could not load plugin.json from: {}".format(json_path))
            validated_data["name"] = json.get("name", json_path.split("/")[-2])
            validated_data["description"] = json.get("description", "")
            validated_data["config_schema"] = json.get("config", {})

        if len(Plugin.objects.filter(name=validated_data["name"])) > 0:
            raise ValidationError('Plugin with name "{}" already installed!'.format(validated_data["name"]))

        if not local_plugin:
            validated_data["archive"] = download_plugin_github_zip(validated_data["url"], validated_data["tag"])

        validated_data["from_web"] = True
        plugin = super().create(validated_data)
        reload_plugins_on_workers()
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        validated_data["archive"] = download_plugin_github_zip(plugin.url, plugin.tag)
        response = super().update(plugin, validated_data)
        reload_plugins_on_workers()
        return response


class PluginViewSet(viewsets.ModelViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "get" or self.action == "list":  # type: ignore
            if can_install_plugins_via_api() or can_configure_plugins_via_api():
                return queryset
        else:
            if can_install_plugins_via_api():
                # block update/delete for plugins that come from posthog.json
                return queryset.filter(from_json=False)
        return queryset.none()

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request):
        if not can_install_plugins_via_api():
            raise ValidationError("Plugin installation via the web is disabled!")
        url = "https://raw.githubusercontent.com/PostHog/plugins/main/repository.json"
        plugins = requests.get(url)
        return Response(json.loads(plugins.text))

    @action(methods=["GET"], detail=False)
    def status(self, request: request.Request):
        if not can_install_plugins_via_api():
            raise ValidationError("Plugin installation via the web is disabled!")

        ping = get_client().get("@posthog-plugin-server/ping")
        if ping:
            ping_datetime = parser.isoparse(ping)
            if ping_datetime > now() - relativedelta(seconds=30):
                return Response({"status": "online"})

        return Response({"status": "offline"})

    def destroy(self, request: request.Request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)
        reload_plugins_on_workers()
        return response


class PluginConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginConfig
        fields = ["id", "plugin", "enabled", "order", "config", "error"]
        read_only_fields = ["id"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:
        if not can_configure_plugins_via_api():
            raise ValidationError("Plugin configuration via the web is disabled!")
        request = self.context["request"]
        validated_data["team"] = request.user.team
        plugin_config = super().create(validated_data)
        reload_plugins_on_workers()
        return plugin_config

    def update(self, plugin_config: PluginConfig, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:  # type: ignore
        validated_data.pop("plugin", None)
        response = super().update(plugin_config, validated_data)
        reload_plugins_on_workers()
        return response


class PluginConfigViewSet(viewsets.ModelViewSet):
    queryset = PluginConfig.objects.all()
    serializer_class = PluginConfigSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if can_configure_plugins_via_api():
            return queryset.filter(team_id=self.request.user.team.pk)
        return queryset.none()

    # we don't use this endpoint, but have something anyway to prevent team leakage
    def destroy(self, request: request.Request, pk=None) -> Response:  # type: ignore
        plugin_config = PluginConfig.objects.get(team=request.user.team, pk=pk)
        plugin_config.enabled = False
        plugin_config.save()
        return Response(status=204)

    @action(methods=["GET"], detail=False)
    def global_plugins(self, request: request.Request):
        if not can_configure_plugins_via_api():
            return Response([])

        response = []
        plugin_configs = PluginConfig.objects.filter(team_id=None, enabled=True)  # type: ignore
        for plugin_config in plugin_configs:
            plugin = PluginConfigSerializer(plugin_config).data
            plugin["config"] = None
            plugin["error"] = None
            response.append(plugin)

        return Response(response)
