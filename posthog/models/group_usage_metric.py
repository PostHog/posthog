from django.db import models

from posthog.models.utils import BytecodeModelMixin, UUIDModel


class GroupUsageMetric(UUIDModel, BytecodeModelMixin):
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

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "group_type_index", "name"], name="unique_metric_name")]

    def get_expr(self):
        from posthog.cdp.filters import hog_function_filters_to_expr

        return hog_function_filters_to_expr(self.filters, self.team, {})
