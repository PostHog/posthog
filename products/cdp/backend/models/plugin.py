# DEPRECATED: Plugins are no longer supported — they have been replaced by Hog functions
# (products/cdp/backend/models/hog_functions/). These models remain only so historical rows
# stay readable. Do not add logic or new usages.
from django.db import models

from posthog.models.organization import Organization
from posthog.models.utils import UUIDTModel, sane_repr


class Plugin(models.Model):
    class PluginType(models.TextChoices):
        LOCAL = "local", "local"  # url starts with "file:"
        CUSTOM = (
            "custom",
            "custom",
        )  # github or npm url downloaded as zip or tar.gz into field "archive"
        REPOSITORY = (
            "repository",
            "repository",
        )  # same, but originating from our plugins.json repository
        SOURCE = (
            "source",
            "source",
        )  # coded inside the browser (versioned via plugin_source_version)
        INLINE = (
            "inline",
            "inline",
        )  # Code checked into plugin_server, url starts with "inline:"

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="plugins",
        related_query_name="plugin",
        null=True,
    )
    plugin_type = models.CharField(max_length=200, null=True, blank=True, choices=PluginType, default=None)
    is_global = models.BooleanField(default=False)  # Whether plugin is installed for all orgs
    is_preinstalled = models.BooleanField(default=False)
    is_stateless = models.BooleanField(
        default=False, null=True, blank=True
    )  # Whether plugin can run one VM across teams

    name = models.CharField(max_length=200, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    url = models.CharField(max_length=800, null=True, blank=True, unique=True)
    icon = models.CharField(max_length=800, null=True, blank=True)
    config_schema = models.JSONField(default=dict, blank=True)
    tag = models.CharField(max_length=200, null=True, blank=True)
    archive = models.BinaryField(blank=True, null=True)
    latest_tag = models.CharField(max_length=800, null=True, blank=True)
    latest_tag_checked_at = models.DateTimeField(null=True, blank=True)
    capabilities = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict, null=True, blank=True)
    public_jobs = models.JSONField(default=dict, null=True, blank=True)

    error = models.JSONField(default=None, null=True, blank=True)
    from_json = models.BooleanField(default=False)
    from_web = models.BooleanField(default=False)
    source = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    log_level = models.IntegerField(null=True, blank=True)

    has_private_access = models.ManyToManyField(Organization)

    class Meta:
        db_table = "posthog_plugin"

    __repr__ = sane_repr("id", "name", "organization_id", "is_global")

    def __str__(self) -> str:
        if not self.name:
            return f"ID {self.id}"
        return self.name


class PluginConfig(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True)
    plugin = models.ForeignKey("cdp.Plugin", on_delete=models.CASCADE)
    enabled = models.BooleanField(default=False)
    order = models.IntegerField()
    config = models.JSONField(default=dict)
    error = models.JSONField(default=None, null=True, blank=True)
    web_token = models.CharField(max_length=64, default=None, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.CharField(max_length=1000, null=True, blank=True)
    deleted = models.BooleanField(default=False, null=True)

    filters = models.JSONField(null=True, blank=True)

    match_action = models.ForeignKey(
        "actions.Action",
        on_delete=models.SET_NULL,
        related_name="plugin_configs",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "posthog_pluginconfig"
        indexes = [
            models.Index(fields=["web_token"]),
            models.Index(fields=["enabled"]),
        ]


class PluginAttachment(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, null=True)
    plugin_config = models.ForeignKey("cdp.PluginConfig", on_delete=models.CASCADE, null=True)
    key = models.CharField(max_length=200)
    content_type = models.CharField(max_length=200)
    file_name = models.CharField(max_length=200)
    file_size = models.IntegerField()
    contents = models.BinaryField()

    class Meta:
        db_table = "posthog_pluginattachment"


class PluginStorage(models.Model):
    plugin_config = models.ForeignKey("cdp.PluginConfig", on_delete=models.CASCADE)
    key = models.CharField(max_length=200)
    value = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "posthog_pluginstorage"
        constraints = [
            models.UniqueConstraint(
                fields=["plugin_config_id", "key"],
                name="posthog_unique_plugin_storage_key",
            )
        ]


class PluginSourceFile(UUIDTModel):
    class Meta:
        db_table = "posthog_pluginsourcefile"
        constraints = [models.UniqueConstraint(name="unique_filename_for_plugin", fields=("plugin_id", "filename"))]

    class Status(models.TextChoices):
        LOCKED = "LOCKED", "locked"
        TRANSPILED = "TRANSPILED", "transpiled"
        ERROR = "ERROR", "error"

    plugin = models.ForeignKey("cdp.Plugin", on_delete=models.CASCADE)
    filename = models.CharField(max_length=200, blank=False)
    source = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status, null=True)
    transpiled = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    __repr__ = sane_repr("plugin_id", "filename", "status")
