import json
import re
from typing import Any, Dict, Optional, Set, cast

import requests
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.utils.timezone import now
from rest_framework import request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.celery import app as celery_app
from posthog.models import Plugin, PluginAttachment, PluginConfig, Team
from posthog.models.organization import Organization
from posthog.models.plugin import update_validated_data_from_url
from posthog.permissions import (
    OrganizationMemberPermissions,
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.plugins import can_configure_plugins, can_install_plugins, parse_url
from posthog.plugins.access import can_globally_manage_plugins

# Keep this in sync with: frontend/scenes/plugins/utils.ts
SECRET_FIELD_VALUE = "**************** POSTHOG SECRET FIELD ****************"


def _update_plugin_attachments(request: request.Request, plugin_config: PluginConfig):
    for key, file in request.FILES.items():
        match = re.match(r"^add_attachment\[([^]]+)\]$", key)
        if match:
            _update_plugin_attachment(plugin_config, match.group(1), file)
    for key, file in request.POST.items():
        match = re.match(r"^remove_attachment\[([^]]+)\]$", key)
        if match:
            _update_plugin_attachment(plugin_config, match.group(1), None)


def _update_plugin_attachment(plugin_config: PluginConfig, key: str, file: Optional[UploadedFile]):
    try:
        plugin_attachment = PluginAttachment.objects.get(team=plugin_config.team, plugin_config=plugin_config, key=key)
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


# sending files via a multipart form puts the config JSON in a un-serialized format
def _fix_formdata_config_json(request: request.Request, validated_data: dict):
    if not validated_data.get("config", None) and cast(dict, request.POST).get("config", None):
        validated_data["config"] = json.loads(request.POST["config"])


class PluginsAccessLevelPermission(BasePermission):
    message = "Your organization's plugin access level is insufficient."

    def has_permission(self, request, view) -> bool:
        min_level = (
            Organization.PluginsAccessLevel.CONFIG
            if request.method in SAFE_METHODS
            else Organization.PluginsAccessLevel.INSTALL
        )
        return view.organization.plugins_access_level >= min_level


class PluginOwnershipPermission(BasePermission):
    message = "This plugin installation is managed by another organization."

    def has_object_permission(self, request, view, object) -> bool:
        return view.organization == object.organization


class PluginSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()

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
            "is_global",
            "organization_id",
            "organization_name",
            "capabilities",
            "metrics",
            "public_jobs",
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

    def get_organization_name(self, plugin: Plugin) -> str:
        return plugin.organization.name

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        validated_data["url"] = self.initial_data.get("url", None)
        validated_data["organization_id"] = self.context["organization_id"]
        if validated_data.get("is_global") and not can_globally_manage_plugins(validated_data["organization_id"]):
            raise PermissionDenied("This organization can't manage global plugins!")
        plugin = Plugin.objects.install(**validated_data)
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        context_organization = self.context.get("organization") or Organization.objects.get(
            id=self.context["organization_id"]
        )
        if (
            "is_global" in validated_data
            and context_organization.plugins_access_level < Organization.PluginsAccessLevel.ROOT
        ):
            raise PermissionDenied("This organization can't manage global plugins!")
        return super().update(plugin, validated_data)


class PluginViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        OrganizationMemberPermissions,
        PluginsAccessLevelPermission,
        PluginOwnershipPermission,
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "get" or self.action == "list":
            if can_install_plugins(self.organization) or can_configure_plugins(self.organization):
                return queryset
        else:
            if can_install_plugins(self.organization):
                return queryset
        return queryset.none()

    def filter_queryset_by_parents_lookups(self, queryset):
        parents_query_dict = self.get_parents_query_dict()
        try:
            return queryset.filter(Q(**parents_query_dict) | Q(is_global=True))
        except ValueError:
            raise NotFound()

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request, **kwargs):
        url = "https://raw.githubusercontent.com/PostHog/plugin-repository/main/repository.json"
        plugins = requests.get(url)
        return Response(json.loads(plugins.text))

    @action(methods=["GET"], detail=True)
    def check_for_updates(self, request: request.Request, **kwargs):
        if not can_install_plugins(self.organization):
            raise PermissionDenied("Plugin installation is not available for the current organization!")
        plugin = self.get_object()
        latest_url = parse_url(plugin.url, get_latest_if_none=True)
        plugin.latest_tag = latest_url.get("tag", latest_url.get("version", None))
        plugin.latest_tag_checked_at = now()
        plugin.save()

        return Response({"plugin": PluginSerializer(plugin).data})

    @action(methods=["POST"], detail=True)
    def upgrade(self, request: request.Request, **kwargs):
        plugin: Plugin = self.get_object()
        organization = self.organization
        if plugin.organization != organization:
            raise NotFound()
        if not can_install_plugins(self.organization, plugin.organization_id):
            raise PermissionDenied("Plugin upgrading is not available for the current organization!")
        serializer = PluginSerializer(plugin, context={"organization": organization})
        validated_data = {}
        if plugin.plugin_type != Plugin.PluginType.SOURCE:
            validated_data = update_validated_data_from_url({}, plugin.url)
            serializer.update(plugin, validated_data)
        return Response(serializer.data)

    def destroy(self, request: request.Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        if instance.is_global:
            raise ValidationError("This plugin is marked as global! Make it local before uninstallation")
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginConfigSerializer(serializers.ModelSerializer):
    config = serializers.SerializerMethodField()

    class Meta:
        model = PluginConfig
        fields = ["id", "plugin", "enabled", "order", "config", "error", "team_id"]
        read_only_fields = ["id", "team_id"]

    def get_config(self, plugin_config: PluginConfig):
        attachments = PluginAttachment.objects.filter(plugin_config=plugin_config).only(
            "id", "file_size", "file_name", "content_type"
        )

        new_plugin_config = plugin_config.config.copy()

        secret_fields = _get_secret_fields_for_plugin(plugin_config.plugin)

        # do not send the real value to the client
        for key in secret_fields:
            if new_plugin_config.get(key):
                new_plugin_config[key] = SECRET_FIELD_VALUE

        for attachment in attachments:
            if attachment.key not in secret_fields:
                new_plugin_config[attachment.key] = {
                    "uid": attachment.id,
                    "saved": True,
                    "size": attachment.file_size,
                    "name": attachment.file_name,
                    "type": attachment.content_type,
                }
            else:
                new_plugin_config[attachment.key] = {
                    "uid": -1,
                    "saved": True,
                    "size": -1,
                    "name": SECRET_FIELD_VALUE,
                    "type": "application/octet-stream",
                }

        return new_plugin_config

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:
        if not can_configure_plugins(Team.objects.get(id=self.context["team_id"]).organization_id):
            raise ValidationError("Plugin configuration is not available for the current organization!")
        validated_data["team"] = Team.objects.get(id=self.context["team_id"])
        _fix_formdata_config_json(self.context["request"], validated_data)
        plugin_config = super().create(validated_data)
        _update_plugin_attachments(self.context["request"], plugin_config)
        return plugin_config

    def update(self, plugin_config: PluginConfig, validated_data: Dict, *args: Any, **kwargs: Any) -> PluginConfig:  # type: ignore
        _fix_formdata_config_json(self.context["request"], validated_data)
        validated_data.pop("plugin", None)

        # Keep old value for secret fields if no new value in the request
        secret_fields = _get_secret_fields_for_plugin(plugin_config.plugin)

        if "config" in validated_data:
            for key in secret_fields:
                if validated_data["config"].get(key) is None:  # explicitly checking None to allow ""
                    validated_data["config"][key] = plugin_config.config.get(key)

        response = super().update(plugin_config, validated_data)
        _update_plugin_attachments(self.context["request"], plugin_config)
        return response


class PluginConfigViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = PluginConfig.objects.all()
    serializer_class = PluginConfigSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        OrganizationMemberPermissions,
        TeamMemberAccessPermission,
    ]

    def get_queryset(self):
        if not can_configure_plugins(self.team.organization_id):
            return self.queryset.none()
        return super().get_queryset().order_by("order", "plugin_id")

    # we don't really use this endpoint, but have something anyway to prevent team leakage
    def destroy(self, request: request.Request, pk=None, **kwargs) -> Response:  # type: ignore
        if not can_configure_plugins(self.team.organization_id):
            return Response(status=404)
        plugin_config = PluginConfig.objects.get(team_id=self.team_id, pk=pk)
        plugin_config.enabled = False
        plugin_config.save()
        return Response(status=204)

    @action(methods=["PATCH"], detail=False)
    def rearrange(self, request: request.Request, **kwargs):
        if not can_configure_plugins(self.team.organization_id):
            raise ValidationError("Plugin configuration is not available for the current organization!")

        orders = request.data.get("orders", {})

        plugin_configs = PluginConfig.objects.filter(team_id=self.team.pk, enabled=True)
        plugin_configs_dict = {p.plugin_id: p for p in plugin_configs}
        for plugin_id, order in orders.items():
            plugin_config = plugin_configs_dict.get(int(plugin_id), None)
            if plugin_config and plugin_config.order != order:
                plugin_config.order = order
                plugin_config.save()

        return Response(PluginConfigSerializer(plugin_configs, many=True).data)

    @action(methods=["POST"], detail=True)
    def job(self, request: request.Request, **kwargs):
        if not can_configure_plugins(self.team.organization_id):
            raise ValidationError("Plugin configuration is not available for the current organization!")

        plugin_config_id = self.get_object().id
        job = request.data.get("job", {})

        if "type" not in job:
            raise ValidationError("The job type must be specified!")

        # the plugin server uses "type" for job names but "name" makes for a more friendly API
        job_type = job.get("type")
        job_payload = job.get("payload", {})
        job_op = job.get("operation", "start")

        celery_app.send_task(
            name="posthog.tasks.plugins.plugin_job",
            queue=settings.PLUGINS_CELERY_QUEUE,
            args=[self.team.pk, plugin_config_id, job_type, job_op, job_payload],
        )

        return Response(status=200)


def _get_secret_fields_for_plugin(plugin: Plugin) -> Set[str]:
    # A set of keys for config fields that have secret = true
    secret_fields = set([field["key"] for field in plugin.config_schema if "secret" in field and field["secret"]])
    return secret_fields
