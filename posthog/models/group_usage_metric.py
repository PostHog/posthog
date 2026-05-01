from django.db import models

from posthog.hogql import ast

from posthog.models.utils import BytecodeModelMixin, UUIDModel
from posthog.rbac.decorators import field_access_control


class GroupUsageMetric(UUIDModel, BytecodeModelMixin):
    """
    A usage metric rendered on a Customer Analytics profile.

    Despite the name and the `group_type_index` field, these metrics are NOT group-specific.
    They were originally built for group profiles, but are now applied to both groups and
    persons — every metric defined for a team surfaces on both kinds of profile.
    `group_type_index` is retained for backward compatibility but is effectively unused:
    the query runner ignores it and evaluates every team-owned metric against the current
    entity (group or person).
    """

    class Format(models.TextChoices):
        NUMERIC = "numeric", "numeric"
        CURRENCY = "currency", "currency"

    class Display(models.TextChoices):
        NUMBER = "number", "number"
        SPARKLINE = "sparkline", "sparkline"

    class Math(models.TextChoices):
        COUNT = "count", "count"
        SUM = "sum", "sum"

    class Source(models.TextChoices):
        EVENTS = "events", "events"
        DATA_WAREHOUSE = "data_warehouse", "data_warehouse"

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

    @property
    def source(self) -> str:
        if isinstance(self.filters, dict) and self.filters.get("source") == self.Source.DATA_WAREHOUSE:
            return self.Source.DATA_WAREHOUSE
        return self.Source.EVENTS

    @property
    def is_data_warehouse(self) -> bool:
        return self.source == self.Source.DATA_WAREHOUSE

    def get_expr(self):
        if self.is_data_warehouse:
            return ast.Constant(value=True)

        from posthog.cdp.filters import hog_function_filters_to_expr

        return hog_function_filters_to_expr(self.filters, self.team, {})
