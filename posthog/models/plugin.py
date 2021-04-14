from typing import Any, Dict, List, Optional, cast

from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

from posthog.ee import is_ee_enabled

from .utils import UUIDModel, sane_repr

try:
    from ee.clickhouse.client import sync_execute
except ImportError:
    pass


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
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField(null=True, blank=True)
    url: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    # Describe the fields to ask in the interface; store answers in PluginConfig->config
    # - config_schema = { [fieldKey]: { name: 'api key', type: 'string', default: '', required: true }  }
    config_schema: JSONField = JSONField(default=dict)
    tag: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    archive: models.BinaryField = models.BinaryField(blank=True, null=True)
    source: models.TextField = models.TextField(blank=True, null=True)
    latest_tag: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    latest_tag_checked_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    # DEPRECATED: not used for anything, all install and config errors are in PluginConfig.error
    error: JSONField = JSONField(default=None, null=True)
    # DEPRECATED: these were used when syncing posthog.json with the db on app start
    from_json: models.BooleanField = models.BooleanField(default=False)
    from_web: models.BooleanField = models.BooleanField(default=False)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


class PluginConfig(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    enabled: models.BooleanField = models.BooleanField(default=False)
    order: models.IntegerField = models.IntegerField()
    config: JSONField = JSONField(default=dict)
    # Error when running this plugin on an event (frontend: PluginErrorType)
    # - e.g: "undefined is not a function on index.js line 23"
    # - error = { message: "Exception in processEvent()", time: "iso-string", ...meta }
    error: JSONField = JSONField(default=None, null=True)

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


class PluginLogEntry(UUIDModel):
    class Type(models.TextChoices):
        LOG = "LOG", "log"
        INFO = "INFO", "info"
        WARN = "WARN", "warn"
        ERROR = "ERROR", "error"

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    timestamp: models.DateTimeField = models.DateTimeField(default=timezone.now)
    type: models.CharField = models.CharField(max_length=20, choices=Type.choices)
    message: models.TextField = models.TextField()
    instance_id: models.UUIDField = models.UUIDField()

    def __str__(self):
        return f"[{self.timestamp.isoformat()}] {self.type}: {self.message}"

    __repr__ = sane_repr("team_id", "plugin_id", "timestamp", "type", "message")


def fetch_plugin_log_entries(
    *,
    team_id: Optional[int],
    plugin_id: Optional[int] = None,
    after: Optional[timezone.datetime] = None,
    before: Optional[timezone.datetime] = None,
) -> List[PluginLogEntry]:
    plugin_log_entries: List[PluginLogEntry] = []

    if is_ee_enabled():
        clickhouse_where_parts: List[str] = []
        clickhouse_kwargs: Dict[str, Any] = {}
        if team_id is not None:
            clickhouse_where_parts.append("team_id = %(team_id)s")
            clickhouse_kwargs["team_id"] = team_id
        if plugin_id is not None:
            clickhouse_where_parts.append("AND plugin_id = %(plugin_id)s")
            clickhouse_kwargs["plugin_id"] = plugin_id
        if after is not None:
            clickhouse_where_parts.append("AND timestamp > toDateTime(%(after)s)")
            clickhouse_kwargs["after"] = after.isoformat()
        if before is not None:
            clickhouse_where_parts.append("AND timestamp < toDateTime(%(before)s)")
            clickhouse_kwargs["before"] = before.isoformat()
        clickhouse_query = f"""
            SELECT id, team_id, plugin_id, timestamp, type, message, instance_id FROM plugin_log_entries
            WHERE {' AND '.join(clickhouse_where_parts)} ORDER BY timestamp DESC
        """
        plugin_log_entries.extend(cast(List[PluginLogEntry], sync_execute(clickhouse_query, clickhouse_kwargs)))

    # Postgres is always queried in case a switch was made from ClickHouse and logs in Postgros are still relevant
    filter_kwargs: Dict[str, Any] = {}
    if team_id is not None:
        filter_kwargs["team_id"] = team_id
    if plugin_id is not None:
        filter_kwargs["plugin_id"] = plugin_id
    if after is not None:
        filter_kwargs["timestamp__gt"] = after
    if before is not None:
        filter_kwargs["timestamp__lte"] = before
    plugin_log_entries.extend(PluginLogEntry.objects.order_by("-timestamp").filter(**filter_kwargs))

    return plugin_log_entries
