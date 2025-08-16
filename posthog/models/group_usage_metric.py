from django.db import models

from posthog.models.utils import UUID7Model


class GroupUsageMetric(UUID7Model):
    class Format(models.TextChoices):
        NUMERIC = "numeric", "numeric"
        CURRENCY = "currency", "currency"

    class Interval(models.IntegerChoices):
        WEEK = 7
        MONTH = 30
        QUARTER = 90

    class Display(models.TextChoices):
        NUMBER = "number", "number"
        SPARKLINE = "sparkline", "sparkline"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    group_type_index = models.IntegerField()
    name = models.CharField("Name", max_length=255)
    format = models.CharField(choices=Format.choices, default=Format.NUMERIC, max_length=64)
    interval = models.IntegerField(choices=Interval.choices, default=Interval.WEEK)
    display = models.CharField(choices=Display.choices, default=Display.NUMBER, max_length=64)
    filters = models.JSONField(null=True, blank=True)
    bytecode = models.JSONField(null=True, blank=True)
    bytecode_error = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "group_type_index", "name"], name="unique_metric_name")]
