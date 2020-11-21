import json
import os
import re
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields import JSONField
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.utils.timezone import now
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.models.plugin import Plugin, PluginAttachment, PluginConfig
from posthog.plugins import (
    can_configure_plugins_via_api,
    can_install_plugins_via_api,
    download_plugin_archive,
    get_json_from_archive,
    parse_url,
    reload_plugins_on_workers,
)
from posthog.plugins.utils import load_json_file
from posthog.redis import get_client


class PluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plugin
        fields = ["id", "name", "description", "url", "config_schema", "tag", "error"]
        read_only_fields = ["id", "name", "description", "config_schema", "tag", "error"]

    def get_error(self, plugin: Plugin) -> Optional[JSONField]:
        if plugin.error and can_install_plugins_via_api():
            return plugin.error
        return None

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        if not can_install_plugins_via_api():
            raise ValidationError("Plugin installation via the web is disabled!")
        validated_data = self._get_validated_data_for_url(validated_data["url"])
        if len(Plugin.objects.filter(name=validated_data["name"])) > 0:
            raise ValidationError('Plugin with name "{}" already installed!'.format(validated_data["name"]))
        plugin = super().create(validated_data)
        reload_plugins_on_workers()
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        if not can_install_plugins_via_api():
            raise ValidationError("Plugin upgrades via the web are disabled!")
        validated_data = self._get_validated_data_for_url(validated_data["url"])
        response = super().update(plugin, validated_data)
        reload_plugins_on_workers()
        return response

    def _get_validated_data_for_url(self, url: str) -> Dict:
        validated_data: Dict[str, Any] = {}
        if url.startswith("file:"):
            plugin_path = url[5:]
            json_path = os.path.join(plugin_path, "plugin.json")
            json = load_json_file(json_path)
            if not json:
                raise ValidationError("Could not load plugin.json from: {}".format(json_path))
            validated_data["url"] = url
            validated_data["tag"] = None
            validated_data["archive"] = None
            validated_data["name"] = json.get("name", json_path.split("/")[-2])
            validated_data["description"] = json.get("description", "")
            validated_data["config_schema"] = json.get("config", {})
        else:
            parsed_url = parse_url(url, get_latest_if_none=True)
            if parsed_url:
                validated_data["url"] = parsed_url["root_url"]
                validated_data["tag"] = parsed_url.get("version", parsed_url.get("tag", None))
                validated_data["archive"] = download_plugin_archive(validated_data["url"], validated_data["tag"])
                plugin_json = get_json_from_archive(validated_data["archive"], "plugin.json")
                if not plugin_json:
                    raise ValidationError("Could not find plugin.json in the plugin")
                validated_data["name"] = plugin_json["name"]
                validated_data["description"] = plugin_json.get("description", "")
                validated_data["config_schema"] = plugin_json.get("config", {})
            else:
                raise ValidationError("Must be a GitHub repository or a NPM package URL!")

        return validated_data


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
                return queryset
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
    config = serializers.SerializerMethodField()

    class Meta:
        model = PluginConfig
        fields = ["id", "plugin", "enabled", "order", "config", "error"]
        read_only_fields = ["id"]

    def get_config(self, plugin_config: PluginConfig):
        attachments = PluginAttachment.objects.filter(plugin_config=plugin_config).only(
            "id", "file_size", "file_name", "content_type"
        )
        new_plugin_config = plugin_config.config.copy()
        for attachment in attachments:
            new_plugin_config[attachment.key] = {
                "uid": attachment.id,
                "saved": True,
                "size": attachment.file_size,
                "name": attachment.file_name,
                "type": attachment.content_type,
            }
        return new_plugin_config

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:
        if not can_configure_plugins_via_api():
            raise ValidationError("Plugin configuration via the web is disabled!")
        request = self.context["request"]
        validated_data["team"] = request.user.team
        self._fix_formdata_config_json(validated_data)
        plugin_config = super().create(validated_data)
        self._update_plugin_attachments(plugin_config)
        reload_plugins_on_workers()
        return plugin_config

    def update(self, plugin_config: PluginConfig, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:  # type: ignore
        self._fix_formdata_config_json(validated_data)
        validated_data.pop("plugin", None)
        response = super().update(plugin_config, validated_data)
        self._update_plugin_attachments(plugin_config)
        reload_plugins_on_workers()
        return response

    # sending files via a multipart form puts the config JSON in a un-serialized format
    def _fix_formdata_config_json(self, validated_data: dict):
        request = self.context["request"]
        if not validated_data.get("config", None) and request.POST.get("config", None):
            validated_data["config"] = json.loads(request.POST["config"])

    def _update_plugin_attachments(self, plugin_config: PluginConfig):
        request = self.context["request"]
        for key, file in request.FILES.items():
            match = re.match(r"^add_attachment\[([^]]+)\]$", key)
            if match:
                self._update_plugin_attachment(plugin_config, match.group(1), file)
        for key, file in request.POST.items():
            match = re.match(r"^remove_attachment\[([^]]+)\]$", key)
            if match:
                self._update_plugin_attachment(plugin_config, match.group(1), None)

    def _update_plugin_attachment(self, plugin_config: PluginConfig, key: str, file: Optional[UploadedFile]):
        try:
            plugin_attachment = PluginAttachment.objects.get(
                team=plugin_config.team, plugin_config=plugin_config, key=key
            )
            if file:
                plugin_attachment.content_type = file.content_type
                plugin_attachment.file_name = file.name
                plugin_attachment.file_size = file.size
                plugin_attachment.contents = file.file.read()
                plugin_attachment.save()
            else:
                plugin_attachment.delete()
        except ObjectDoesNotExist:
            if file:
                PluginAttachment.objects.create(
                    team=plugin_config.team,
                    plugin_config=plugin_config,
                    key=key,
                    content_type=str(file.content_type),
                    file_name=file.name,
                    file_size=file.size,
                    contents=file.file.read(),
                )


class PluginConfigViewSet(viewsets.ModelViewSet):
    queryset = PluginConfig.objects.all()
    serializer_class = PluginConfigSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if can_configure_plugins_via_api():
            return queryset.filter(team_id=self.request.user.team.pk)
        return queryset.none()

    # we don't really use this endpoint, but have something anyway to prevent team leakage
    def destroy(self, request: request.Request, pk=None) -> Response:  # type: ignore
        if not can_configure_plugins_via_api():
            return Response(status=404)
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
