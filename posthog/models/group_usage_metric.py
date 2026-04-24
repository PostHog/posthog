from django.db import models

from posthog.models.utils import BytecodeModelMixin, UUIDModel
from posthog.rbac.decorators import field_access_control


class GroupUsageMetric(UUIDModel, BytecodeModelMixin):
    class Format(models.TextChoices):
        NUMERIC = "numeric", "numeric"
        CURRENCY = "currency", "currency"

    class Display(models.TextChoices):
        NUMBER = "number", "number"
        SPARKLINE = "sparkline", "sparkline"

    class Math(models.TextChoices):
        COUNT = "count", "count"
        SUM = "sum", "sum"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    group_type_index = models.IntegerField()
    name = field_access_control(models.CharField("Name", max_length=255), "project", "admin")
    format = field_access_control(
        models.CharField(choices=Format, default=Format.NUMERIC, max_length=64), "project", "admin"
    )
    interval = field_access_control(models.IntegerField(default=7, help_text="In days"), "project", "admin")
    display = field_access_control(
        models.CharField(choices=Display, default=Display.NUMBER, max_length=64), "project", "admin"
    )
    filters = field_access_control(models.JSONField(), "project", "admin")
    math = field_access_control(
        models.CharField(choices=Math.choices, default=Math.COUNT, max_length=16), "project", "admin"
    )
    math_property = field_access_control(models.CharField(max_length=255, null=True, blank=True), "project", "admin")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "group_type_index", "name"], name="unique_metric_name")]

    def get_expr(self):
        from posthog.cdp.filters import hog_function_filters_to_expr

        return hog_function_filters_to_expr(self.filters, self.team, {})
