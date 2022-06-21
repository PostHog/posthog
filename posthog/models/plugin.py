import datetime
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, cast
from uuid import UUID

from django.conf import settings
from django.core import exceptions
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from semantic_version.base import SimpleSpec, Version

from posthog.models.organization import Organization
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.plugins.access import can_configure_plugins, can_install_plugins
from posthog.plugins.reload import reload_plugins_on_workers
from posthog.plugins.utils import (
    download_plugin_archive,
    extract_plugin_code,
    get_file_from_archive,
    load_json_file,
    parse_url,
)
from posthog.version import VERSION

from .utils import UUIDModel, sane_repr

try:
    from posthog.client import sync_execute
except ImportError:
    pass


def raise_if_plugin_installed(url: str, organization_id: str):
    url_without_private_key = url.split("?")[0]
    if (
        Plugin.objects.filter(
            models.Q(url=url_without_private_key) | models.Q(url__startswith=f"{url_without_private_key}?")
        )
        .filter(organization_id=organization_id)
        .exists()
    ):
        raise ValidationError(f'Plugin from URL "{url_without_private_key}" already installed!')


def update_validated_data_from_url(validated_data: Dict[str, Any], url: str) -> Dict[str, Any]:
    """If remote plugin, download the archive and get up-to-date validated_data from there. Returns plugin.json."""
    plugin_json: Optional[Dict[str, Any]]
    if url.startswith("file:"):
        plugin_path = url[5:]
        plugin_json_path = os.path.join(plugin_path, "plugin.json")
        plugin_json = cast(Optional[Dict[str, Any]], load_json_file(plugin_json_path))
        if not plugin_json:
            raise ValidationError(f"Could not load plugin.json from: {plugin_json_path}")
        validated_data["plugin_type"] = "local"
        validated_data["url"] = url
        validated_data["tag"] = None
        validated_data["archive"] = None
        validated_data["name"] = plugin_json.get("name", plugin_json_path.split("/")[-2])
        validated_data["description"] = plugin_json.get("description", "")
        validated_data["config_schema"] = plugin_json.get("config", [])
        validated_data["public_jobs"] = plugin_json.get("publicJobs", {})
        posthog_version = plugin_json.get("posthogVersion", None)
        validated_data["is_stateless"] = plugin_json.get("stateless", False)
    else:
        parsed_url = parse_url(url, get_latest_if_none=True)
        if parsed_url:
            validated_data["url"] = parsed_url["root_url"]
            validated_data["tag"] = parsed_url.get("tag", None)
            validated_data["archive"] = download_plugin_archive(validated_data["url"], validated_data["tag"])
            plugin_json = cast(
                Optional[Dict[str, Any]], get_file_from_archive(validated_data["archive"], "plugin.json")
            )
            if not plugin_json:
                raise ValidationError("Could not find plugin.json in the plugin")
            validated_data["name"] = plugin_json["name"]
            validated_data["description"] = plugin_json.get("description", "")
            validated_data["config_schema"] = plugin_json.get("config", [])
            validated_data["public_jobs"] = plugin_json.get("publicJobs", {})
            posthog_version = plugin_json.get("posthogVersion", None)
            validated_data["is_stateless"] = plugin_json.get("stateless", False)

            if validated_data["is_stateless"] and len(validated_data["config_schema"]) > 0:
                raise ValidationError("Stateless plugins cannot have a config!")
        else:
            raise ValidationError("Must be a GitHub/GitLab repository or a npm package URL!")

        # Keep plugin type as "repository" or reset to "custom" if it was something else.
        if (
            validated_data.get("plugin_type", None) != Plugin.PluginType.CUSTOM
            and validated_data.get("plugin_type", None) != Plugin.PluginType.REPOSITORY
        ):
            validated_data["plugin_type"] = Plugin.PluginType.CUSTOM

    if posthog_version and not settings.MULTI_TENANCY:
        try:
            spec = SimpleSpec(posthog_version.replace(" ", ""))
        except ValueError:
            raise ValidationError(f'Invalid PostHog semantic version requirement "{posthog_version}"!')
        if not (Version(VERSION) in spec):
            raise ValidationError(
                f'Currently running PostHog version {VERSION} does not match this plugin\'s semantic version requirement "{posthog_version}".'
            )

    return plugin_json


class PluginManager(models.Manager):
    def install(self, **kwargs) -> "Plugin":
        if "organization_id" not in kwargs and "organization" in kwargs:
            kwargs["organization_id"] = kwargs["organization"].id
        plugin_json: Optional[Dict[str, Any]] = None
        if kwargs.get("plugin_type", None) != Plugin.PluginType.SOURCE:
            plugin_json = update_validated_data_from_url(kwargs, kwargs["url"])
            raise_if_plugin_installed(kwargs["url"], kwargs["organization_id"])
        plugin = Plugin.objects.create(**kwargs)
        if plugin_json:
            PluginSourceFile.objects.sync_from_plugin_archive(plugin, plugin_json)
        reload_plugins_on_workers()
        return plugin


class Plugin(models.Model):
    class PluginType(models.TextChoices):
        LOCAL = "local", "local"  # url starts with "file:"
        CUSTOM = "custom", "custom"  # github or npm url downloaded as zip or tar.gz into field "archive"
        REPOSITORY = "repository", "repository"  # same, but originating from our plugins.json repository
        SOURCE = "source", "source"  # coded inside the browser (versioned via plugin_source_version)

    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="plugins", related_query_name="plugin"
    )
    plugin_type: models.CharField = models.CharField(
        max_length=200, null=True, blank=True, choices=PluginType.choices, default=None
    )
    is_global: models.BooleanField = models.BooleanField(default=False)  # Whether plugin is installed for all orgs
    is_preinstalled: models.BooleanField = models.BooleanField(default=False)
    is_stateless: models.BooleanField = models.BooleanField(
        default=False, null=True, blank=True
    )  # Whether plugin can run one VM across teams

    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField(null=True, blank=True)
    url: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    # Describe the fields to ask in the interface; store answers in PluginConfig->config
    # - config_schema = { [fieldKey]: { name: 'api key', type: 'string', default: '', required: true }  }
    config_schema: models.JSONField = models.JSONField(default=dict)
    tag: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    archive: models.BinaryField = models.BinaryField(blank=True, null=True)
    latest_tag: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    latest_tag_checked_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    capabilities: models.JSONField = models.JSONField(default=dict)
    metrics: models.JSONField = models.JSONField(default=dict, null=True)
    public_jobs: models.JSONField = models.JSONField(default=dict, null=True)

    # DEPRECATED: not used for anything, all install and config errors are in PluginConfig.error
    error: models.JSONField = models.JSONField(default=None, null=True)
    # DEPRECATED: this was used when syncing posthog.json with the db on app start
    from_json: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED: this was used when syncing posthog.json with the db on app start
    from_web: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED: using PluginSourceFile model instead
    source: models.TextField = models.TextField(blank=True, null=True)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    log_level: models.IntegerField = models.IntegerField(null=True, blank=True)

    objects: PluginManager = PluginManager()

    def get_default_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        config_schema = self.config_schema
        if isinstance(config_schema, dict):
            for key, config_entry in config_schema.items():
                default = config_entry.get("default")
                if default is not None:
                    config[key] = default
        elif isinstance(config_schema, list):
            for config_entry in config_schema:
                default = config_entry.get("default")
                if default is not None:
                    config[config_entry["key"]] = default
        return config

    def __str__(self) -> str:
        if not self.name:
            return f"ID {self.id}"
        return self.name

    __repr__ = sane_repr("id", "name", "organization_id", "is_global")


class PluginConfig(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    enabled: models.BooleanField = models.BooleanField(default=False)
    order: models.IntegerField = models.IntegerField()
    config: models.JSONField = models.JSONField(default=dict)
    # Error when running this plugin on an event (frontend: PluginErrorType)
    # - e.g: "undefined is not a function on index.js line 23"
    # - error = { message: "Exception in processEvent()", time: "iso-string", ...meta }
    error: models.JSONField = models.JSONField(default=None, null=True)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


class PluginAttachment(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin_config: models.ForeignKey = models.ForeignKey("PluginConfig", on_delete=models.CASCADE, null=True)
    key: models.CharField = models.CharField(max_length=200)
    content_type: models.CharField = models.CharField(max_length=200)
    file_name: models.CharField = models.CharField(max_length=200)
    file_size: models.IntegerField = models.IntegerField()
    contents: models.BinaryField = models.BinaryField()


class PluginStorage(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plugin_config_id", "key"], name="posthog_unique_plugin_storage_key")
        ]

    plugin_config: models.ForeignKey = models.ForeignKey("PluginConfig", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=200)
    value: models.TextField = models.TextField(blank=True, null=True)


class PluginLogEntrySource(str, Enum):
    SYSTEM = "SYSTEM"
    PLUGIN = "PLUGIN"
    CONSOLE = "CONSOLE"


class PluginLogEntryType(str, Enum):
    DEBUG = "DEBUG"
    LOG = "LOG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class PluginSourceFileManager(models.Manager):
    def sync_from_plugin_archive(
        self, plugin: Plugin, plugin_json_parsed: Optional[Dict[str, Any]] = None
    ) -> Tuple["PluginSourceFile", Optional["PluginSourceFile"], Optional["PluginSourceFile"]]:
        """Create PluginSourceFile objects from a plugin that has an archive.

        If plugin.json has already been parsed before this is called, its value can be passed in as an optimization."""
        try:
            plugin_json, index_ts, frontend_tsx = extract_plugin_code(plugin.archive, plugin_json_parsed)
        except ValueError as e:
            raise exceptions.ValidationError(f"{e} in plugin {plugin}")
        # If frontend.tsx or index.ts are not present in the archive, make sure they aren't found in the DB either
        filenames_to_delete = []
        # Save plugin.json
        plugin_json_instance, _ = PluginSourceFile.objects.update_or_create(
            plugin=plugin, filename="plugin.json", defaults={"source": plugin_json}
        )
        # Save frontend.tsx
        frontend_tsx_instance: Optional["PluginSourceFile"] = None
        if frontend_tsx is not None:
            frontend_tsx_instance, _ = PluginSourceFile.objects.update_or_create(
                plugin=plugin, filename="frontend.tsx", defaults={"source": frontend_tsx}
            )
        else:
            filenames_to_delete.append("frontend.tsx")
        # Save index.ts
        index_ts_instance: Optional["PluginSourceFile"] = None
        if index_ts is not None:
            # The original name of the file is not preserved, but this greatly simplifies the rest of the code,
            # and we don't need to model the whole filesystem (at this point)
            index_ts_instance, _ = PluginSourceFile.objects.update_or_create(
                plugin=plugin, filename="index.ts", defaults={"source": index_ts}
            )
        else:
            filenames_to_delete.append("index.ts")
        # Make sure files are gone
        PluginSourceFile.objects.filter(plugin=plugin, filename__in=filenames_to_delete).delete()
        return plugin_json_instance, index_ts_instance, frontend_tsx_instance


class PluginSourceFile(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(name="unique_filename_for_plugin", fields=("plugin_id", "filename")),
        ]

    class Status(models.TextChoices):
        LOCKED = "LOCKED", "locked"
        TRANSPILED = "TRANSPILED", "transpiled"
        ERROR = "ERROR", "error"

    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    filename: models.CharField = models.CharField(max_length=200, blank=False)
    # "source" can be null if we're only using this model to cache transpiled code from a ".zip"
    source: models.TextField = models.TextField(blank=True, null=True)
    status: models.CharField = models.CharField(max_length=20, choices=Status.choices, null=True)
    transpiled: models.TextField = models.TextField(blank=True, null=True)
    error: models.TextField = models.TextField(blank=True, null=True)

    objects: PluginSourceFileManager = PluginSourceFileManager()

    __repr__ = sane_repr("plugin_id", "filename", "status")


@dataclass(frozen=True)
class PluginLogEntry:
    id: UUID
    team_id: int
    plugin_id: int
    plugin_config_id: int
    timestamp: datetime.datetime
    source: PluginLogEntrySource
    type: PluginLogEntryType
    message: str
    instance_id: UUID


def fetch_plugin_log_entries(
    *,
    team_id: Optional[int] = None,
    plugin_config_id: Optional[int] = None,
    after: Optional[timezone.datetime] = None,
    before: Optional[timezone.datetime] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    type_filter: List[PluginLogEntryType] = [],
) -> List[PluginLogEntry]:
    clickhouse_where_parts: List[str] = []
    clickhouse_kwargs: Dict[str, Any] = {}
    if team_id is not None:
        clickhouse_where_parts.append("team_id = %(team_id)s")
        clickhouse_kwargs["team_id"] = team_id
    if plugin_config_id is not None:
        clickhouse_where_parts.append("plugin_config_id = %(plugin_config_id)s")
        clickhouse_kwargs["plugin_config_id"] = plugin_config_id
    if after is not None:
        clickhouse_where_parts.append("timestamp > toDateTime64(%(after)s, 6)")
        clickhouse_kwargs["after"] = after.isoformat().replace("+00:00", "")
    if before is not None:
        clickhouse_where_parts.append("timestamp < toDateTime64(%(before)s, 6)")
        clickhouse_kwargs["before"] = before.isoformat().replace("+00:00", "")
    if search:
        clickhouse_where_parts.append("message ILIKE %(search)s")
        clickhouse_kwargs["search"] = f"%{search}%"
    if len(type_filter) > 0:
        clickhouse_where_parts.append("type in %(types)s")
        clickhouse_kwargs["types"] = type_filter
    clickhouse_query = f"""
        SELECT id, team_id, plugin_id, plugin_config_id, timestamp, source, type, message, instance_id FROM plugin_log_entries
        WHERE {' AND '.join(clickhouse_where_parts)} ORDER BY timestamp DESC {f'LIMIT {limit}' if limit else ''}
    """
    return [PluginLogEntry(*result) for result in cast(list, sync_execute(clickhouse_query, clickhouse_kwargs))]


@receiver(models.signals.post_save, sender=Organization)
def preinstall_plugins_for_new_organization(sender, instance: Organization, created: bool, **kwargs):
    if created and not settings.MULTI_TENANCY and can_install_plugins(instance):
        for plugin_url in settings.PLUGINS_PREINSTALLED_URLS:
            try:
                Plugin.objects.install(
                    organization=instance,
                    plugin_type=Plugin.PluginType.REPOSITORY,
                    url=plugin_url,
                    is_preinstalled=True,
                )
            except Exception as e:
                print(
                    f"⚠️ Cannot preinstall plugin from {plugin_url}, skipping it for organization {instance.name}:\n", e
                )


@receiver(models.signals.post_save, sender=Team)
def enable_preinstalled_plugins_for_new_team(sender, instance: Team, created: bool, **kwargs):
    if created and can_configure_plugins(instance.organization):
        for order, preinstalled_plugin in enumerate(Plugin.objects.filter(is_preinstalled=True)):

            PluginConfig.objects.create(
                team=instance,
                plugin=preinstalled_plugin,
                enabled=True,
                order=order,
                config=preinstalled_plugin.get_default_config(),
            )


@mutable_receiver([post_save, post_delete], sender=Plugin)
def plugin_reload_needed(sender, instance, created=None, **kwargs):
    # Newly created plugins don't have a config yet, so no need to reload
    if not created:
        reload_plugins_on_workers()


@mutable_receiver([post_save, post_delete], sender=PluginConfig)
def plugin_config_reload_needed(sender, instance, created=None, **kwargs):
    reload_plugins_on_workers()


@mutable_receiver([post_save, post_delete], sender=PluginAttachment)
def plugin_attachement_reload_needed(sender, instance, created=None, **kwargs):
    reload_plugins_on_workers()
