import json
from typing import Any, Dict

import requests
from django.db.models import QuerySet
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.models import Plugin
from posthog.plugins import Plugins


class PluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plugin
        fields = ["id", "name", "description", "url", "enabled", "order", "config", "configSchema", "tag"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        request = self.context["request"]
        validated_data["archive"] = self._download_github_zip(validated_data["url"], validated_data["tag"])
        plugin = Plugin.objects.create(team=request.user.team, **validated_data)
        Plugins().publish_reload_command()
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        plugin.name = validated_data.get("name", plugin.name)
        plugin.url = validated_data.get("url", plugin.url)
        plugin.enabled = validated_data.get("enabled", plugin.enabled)
        plugin.config = validated_data.get("config", plugin.config)
        plugin.order = validated_data.get("order", plugin.order)
        if plugin.tag != validated_data.get("tag", plugin.tag):
            plugin.tag = validated_data.get("tag", plugin.tag)
            plugin.archive = self._download_github_zip(plugin.url, plugin.tag)
        plugin.save()
        Plugins().publish_reload_command()
        return plugin

    def _download_github_zip(self, repo: str, tag: str):
        URL_TEMPLATE = "{repo}/archive/{tag}.zip"
        url = URL_TEMPLATE.format(repo=repo, tag=tag)
        response = requests.get(url)
        if not response.ok:
            raise Exception("Could not download archive from GitHub")
        return response.content


class PluginViewSet(viewsets.ModelViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset.filter(team=self.request.user.team).order_by("order")

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request):
        url = "https://raw.githubusercontent.com/PostHog/plugins/main/plugins.json"
        plugins = requests.get(url)
        return Response(json.loads(plugins.text))
