from django.contrib.postgres.fields import JSONField
from django.db import models


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
    # Error installing or configuring this plugin (frontend: PluginErrorType)
    # - e.g: "could not find plugin.json" / "syntax error in index.js")
    # - error = { message: "Could not find plugin.json", time: "iso-string", ...meta }
    error: JSONField = JSONField(default=None, null=True)
    # DEPRECATED: these were used when syncing posthog.json with the db on app start
    from_json: models.BooleanField = models.BooleanField(default=False)
    from_web: models.BooleanField = models.BooleanField(default=False)


class PluginConfig(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    enabled: models.BooleanField = models.BooleanField(default=False)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    config: JSONField = JSONField(default=dict)
    # Error when running this plugin on an event (frontend: PluginErrorType)
    # - e.g: "undefined is not a function on index.js line 23"
    # - error = { message: "Exception in processEvent()", time: "iso-string", ...meta }
    error: JSONField = JSONField(default=None, null=True)


class PluginAttachment(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin_config: models.ForeignKey = models.ForeignKey("PluginConfig", on_delete=models.CASCADE)
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
