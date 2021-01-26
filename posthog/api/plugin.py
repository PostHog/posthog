import json
import os
import re
from typing import Any, Dict, Optional

import requests
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.utils.timezone import now
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Plugin, PluginAttachment, PluginConfig, Team
from posthog.permissions import ProjectMembershipNecessaryPermissions
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
    url = serializers.SerializerMethodField()

    class Meta:
        model = Plugin
        fields = [
            "id",
            "plugin_type",
            "name",
            "description",
            "url",
            "config_schema",
            "tag",
            "source",
            "latest_tag",
        ]
        read_only_fields = ["id", "latest_tag"]

    def get_url(self, plugin: Plugin) -> Optional[str]:
        # remove ?private_token=... from url
        return str(plugin.url).split("?")[0] if plugin.url else None

    def get_latest_tag(self, plugin: Plugin) -> Optional[str]:
        if not plugin.latest_tag or not plugin.latest_tag_checked_at:
            return None

        if plugin.latest_tag != plugin.tag or plugin.latest_tag_checked_at > now() - relativedelta(seconds=60 * 30):
            return str(plugin.latest_tag)

        return None

    def _raise_if_plugin_installed(self, url: str):
        url_without_private_key = url.split("?")[0]
        if Plugin.objects.filter(
            Q(url=url_without_private_key) | Q(url__startswith="{}?".format(url_without_private_key))
        ).exists():
            raise ValidationError('Plugin from URL "{}" already installed!'.format(url_without_private_key))

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        validated_data["url"] = self.initial_data.get("url", None)
        if not can_install_plugins_via_api(self.context["organization_id"]):
            raise ValidationError("Plugin installation via the web is disabled!")
        if validated_data.get("plugin_type", None) != Plugin.PluginType.SOURCE:
            self._update_validated_data_from_url(validated_data, validated_data["url"])
            self._raise_if_plugin_installed(validated_data["url"])
        validated_data["organization_id"] = self.context["organization_id"]
        plugin = super().create(validated_data)
        reload_plugins_on_workers()
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        if not can_install_plugins_via_api(self.context["organization_id"]):
            raise ValidationError("Plugin upgrades via the web are disabled!")
        if plugin.plugin_type != Plugin.PluginType.SOURCE:
            validated_data = self._update_validated_data_from_url({}, plugin.url)
            response = super().update(plugin, validated_data)
            reload_plugins_on_workers()
        return response

    # If remote plugin, download the archive and get up-to-date validated_data from there.
    def _update_validated_data_from_url(self, validated_data: Dict[str, Any], url: str) -> Dict:
        if url.startswith("file:"):
            plugin_path = url[5:]
            json_path = os.path.join(plugin_path, "plugin.json")
            json = load_json_file(json_path)
            if not json:
                raise ValidationError("Could not load plugin.json from: {}".format(json_path))
            validated_data["plugin_type"] = "local"
            validated_data["url"] = url
            validated_data["tag"] = None
            validated_data["archive"] = None
            validated_data["name"] = json.get("name", json_path.split("/")[-2])
            validated_data["description"] = json.get("description", "")
            validated_data["config_schema"] = json.get("config", {})
            validated_data["source"] = None
        else:
            parsed_url = parse_url(url, get_latest_if_none=True)
            if parsed_url:
                validated_data["url"] = parsed_url["root_url"]
                validated_data["tag"] = parsed_url.get("tag", None)
                validated_data["archive"] = download_plugin_archive(validated_data["url"], validated_data["tag"])
                plugin_json = get_json_from_archive(validated_data["archive"], "plugin.json")
                if not plugin_json:
                    raise ValidationError("Could not find plugin.json in the plugin")
                validated_data["name"] = plugin_json["name"]
                validated_data["description"] = plugin_json.get("description", "")
                validated_data["config_schema"] = plugin_json.get("config", {})
                validated_data["source"] = None
            else:
                raise ValidationError("Must be a GitHub/GitLab repository or a npm package URL!")

            # Keep plugin type as "repository" or reset to "custom" if it was something else.
            if (
                validated_data.get("plugin_type", None) != Plugin.PluginType.CUSTOM
                and validated_data.get("plugin_type", None) != Plugin.PluginType.REPOSITORY
            ):
                validated_data["plugin_type"] = Plugin.PluginType.CUSTOM

        return validated_data


class PluginViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "get" or self.action == "list":
            if can_install_plugins_via_api(self.organization) or can_configure_plugins_via_api(self.organization):
                return queryset
        else:
            if can_install_plugins_via_api(self.organization):
                return queryset
        return queryset.none()

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request, **kwargs):
        if not can_install_plugins_via_api(self.organization):
            raise ValidationError("Plugin installation via the web is disabled!")
        url = "https://raw.githubusercontent.com/PostHog/plugin-repository/main/repository.json"
        plugins = requests.get(url)
        return Response(json.loads(plugins.text))

    @action(methods=["GET"], detail=False)
    def status(self, request: request.Request, **kwargs):
        if not can_install_plugins_via_api(self.organization):
            raise ValidationError("Plugin installation via the web is disabled!")

        ping = get_client().get("@posthog-plugin-server/ping")
        if ping:
            ping_datetime = parser.isoparse(ping)
            if ping_datetime > now() - relativedelta(seconds=30):
                return Response({"status": "online"})

        return Response({"status": "offline"})

    @action(methods=["GET"], detail=True)
    def check_for_updates(self, request: request.Request, **kwargs):
        if not can_install_plugins_via_api(self.organization):
            raise ValidationError("Plugin installation via the web is disabled!")

        plugin = self.get_object()
        latest_url = parse_url(plugin.url, get_latest_if_none=True)
        plugin.latest_tag = latest_url.get("tag", latest_url.get("version", None))
        plugin.latest_tag_checked_at = now()
        plugin.save()

        return Response({"plugin": PluginSerializer(plugin).data})

    def destroy(self, request: request.Request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)
        reload_plugins_on_workers()
        return response


class PluginConfigSerializer(serializers.ModelSerializer):
    config = serializers.SerializerMethodField()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

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
        if not can_configure_plugins_via_api(Team.objects.get(id=self.context["team_id"]).organization_id):
            raise ValidationError("Plugin configuration via the web is disabled!")
        request = self.context["request"]
        validated_data["team"] = Team.objects.get(id=self.context["team_id"])
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


class PluginConfigViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = PluginConfig.objects.all()
    serializer_class = PluginConfigSerializer

    def get_queryset(self):
        if not can_configure_plugins_via_api(self.team.organization_id):
            return self.queryset.none()
        return super().get_queryset()

    # we don't really use this endpoint, but have something anyway to prevent team leakage
    def destroy(self, request: request.Request, pk=None, **kwargs) -> Response:  # type: ignore
        if not can_configure_plugins_via_api(self.team.organization_id):
            return Response(status=404)
        plugin_config = PluginConfig.objects.get(team_id=self.team_id, pk=pk)
        plugin_config.enabled = False
        plugin_config.save()
        return Response(status=204)

    @action(methods=["GET"], detail=False)
    def global_plugins(self, request: request.Request, **kwargs):
        if not can_configure_plugins_via_api(self.team.organization_id):
            return Response([])

        response = []
        plugin_configs = PluginConfig.objects.filter(team_id=None, enabled=True)  # type: ignore
        for plugin_config in plugin_configs:
            plugin = PluginConfigSerializer(plugin_config).data
            plugin["config"] = None
            plugin["error"] = None
            response.append(plugin)

        return Response(response)
