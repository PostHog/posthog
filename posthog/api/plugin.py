import json
from typing import Any, Dict

import requests
from django.conf import settings
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.models import Plugin, PluginConfig
from posthog.plugins import download_plugin_github_zip, reload_plugins_on_workers


class PluginSerializer(serializers.ModelSerializer):
    # read_only=True if plugin is from posthog.json and shouldn't be modified in the interface
    read_only = serializers.SerializerMethodField()

    class Meta:
        model = Plugin
        fields = ["id", "name", "description", "url", "config_schema", "tag", "from_json", "read_only"]
        read_only_fields = ["id", "from_json", "read_only"]

    def get_read_only(self, plugin: Plugin):
        return plugin.from_json

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        if not settings.PLUGINS_INSTALL_FROM_WEB:
            raise ValidationError("Plugin installation via the web is disabled!")
        if len(Plugin.objects.filter(name=validated_data["name"])) > 0:
            raise ValidationError('Plugin with name "{}" already installed!'.format(validated_data["name"]))
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
        if self.action == "get" or self.action == "list":
            if settings.PLUGINS_INSTALL_FROM_WEB or settings.PLUGINS_CONFIGURE_FROM_WEB:
                return queryset
        else:
            if settings.PLUGINS_INSTALL_FROM_WEB:
                # block update/delete for plugins that come from posthog.json
                return queryset.filter(from_json=False)
        return queryset.none()

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request):
        if not settings.PLUGINS_INSTALL_FROM_WEB:
            raise ValidationError("Plugin installation via the web is disabled!")
        url = "https://raw.githubusercontent.com/PostHog/plugins/main/repository.json"
        plugins = requests.get(url)
        return Response(json.loads(plugins.text))

    def destroy(self, request: request.Request, *args, **kwargs) -> Response:  # type: ignore
        response = super().destroy(request, *args, **kwargs)
        reload_plugins_on_workers()
        return response


class PluginConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginConfig
        fields = ["id", "plugin", "enabled", "order", "config"]
        read_only_fields = ["id"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:
        if not settings.PLUGINS_CONFIGURE_FROM_WEB:
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
        if settings.PLUGINS_CONFIGURE_FROM_WEB:
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
        if not settings.PLUGINS_CONFIGURE_FROM_WEB:
            return Response([])

        response = []
        plugin_configs = PluginConfig.objects.filter(team_id=None, enabled=True)  # type: ignore
        for plugin_config in plugin_configs:
            plugin = PluginConfigSerializer(plugin_config).data
            plugin["config"] = None
            response.append(plugin)

        return Response(response)
