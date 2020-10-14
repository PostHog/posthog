from django.contrib.postgres.fields import JSONField
from django.db import models


class Plugin(models.Model):
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField(null=True, blank=True)
    url: models.CharField = models.CharField(max_length=800, null=True, blank=True)
    configSchema: JSONField = JSONField(default=dict)
    tag: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    archive: models.BinaryField = models.BinaryField(blank=True, null=True)
    from_cli: models.BooleanField = models.BooleanField(default=False)
    from_web: models.BooleanField = models.BooleanField(default=False)


class PluginConfig(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    enabled: models.BooleanField = models.BooleanField(default=False)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    config: JSONField = JSONField(default=dict)
