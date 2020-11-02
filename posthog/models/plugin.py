from django.contrib.postgres.fields import JSONField
from django.db import models


class Plugin(models.Model):
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField(null=True, blank=True)
    url: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    # Describe the fields to ask in the interface; store answers in PluginConfig->config
    # - config_schema = { [fieldKey]: { name: 'api key', type: 'string', default: '', required: true }  }
    config_schema: JSONField = JSONField(default=dict)
    tag: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    archive: models.BinaryField = models.BinaryField(blank=True, null=True)
    from_json: models.BooleanField = models.BooleanField(default=False)
    from_web: models.BooleanField = models.BooleanField(default=False)
    # Error installing or configuring this plugin (frontend: PluginErrorType)
    # - e.g: "could not find plugin.json" / "syntax error in index.js")
    # - error = { message: "Could not find plugin.json", time: "iso-string", ...meta }
    error: JSONField = JSONField(default=None, null=True)


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
