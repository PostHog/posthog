from django.db import models

from posthog.models.utils import UUIDModel


class GroupUsageMetric(UUIDModel):
    class Format(models.TextChoices):
        NUMERIC = "numeric", "numeric"
        CURRENCY = "currency", "currency"

    class Display(models.TextChoices):
        NUMBER = "number", "number"
        SPARKLINE = "sparkline", "sparkline"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    group_type_index = models.IntegerField()
    name = models.CharField("Name", max_length=255)
    format = models.CharField(choices=Format.choices, default=Format.NUMERIC, max_length=64)
    interval = models.IntegerField(default=7, help_text="In days")
    display = models.CharField(choices=Display.choices, default=Display.NUMBER, max_length=64)
    filters = models.JSONField()
    bytecode = models.JSONField()
    bytecode_error = models.TextField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "group_type_index", "name"], name="unique_metric_name")]

    def refresh_bytecode(self):
        # TODO(https://github.com/PostHog/posthog/issues/36710): Implement actual conversion from filter to bytecode
        self.bytecode = self.filters

    def save(self, *args, **kwargs):
        self.refresh_bytecode()
        super().save(*args, **kwargs)
