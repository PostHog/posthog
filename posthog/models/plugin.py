from django.contrib.postgres.fields import JSONField
from django.core import validators
from django.db import models


class FileURLField(models.URLField):
    """URL field that accepts URLs that start with http://, https:// and file: only"""

    default_validators = [validators.URLValidator(schemes=["http", "https", "file"])]


class Plugin(models.Model):
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField(null=True, blank=True)
    url: models.CharField = FileURLField(max_length=800, null=True, blank=True)
    config_schema: JSONField = JSONField(default=dict)
    tag: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    archive: models.BinaryField = models.BinaryField(blank=True, null=True)
    from_json: models.BooleanField = models.BooleanField(default=False)
    from_web: models.BooleanField = models.BooleanField(default=False)
    error: JSONField = JSONField(default=None, null=True)


class PluginConfig(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    plugin: models.ForeignKey = models.ForeignKey("Plugin", on_delete=models.CASCADE)
    enabled: models.BooleanField = models.BooleanField(default=False)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    config: JSONField = JSONField(default=dict)
    error: JSONField = JSONField(default=None, null=True)
