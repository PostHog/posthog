from typing import Any, cast

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import GroupUsageMetric

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_DW_FILTER_REQUIRED_FIELDS = ("table_name", "timestamp_field", "key_field")


class GroupUsageMetricSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    name = serializers.CharField(
        max_length=255,
        help_text="Name of the usage metric. Must be unique per group type within the project.",
    )
    format = serializers.ChoiceField(
        choices=GroupUsageMetric.Format.choices,
        default=GroupUsageMetric.Format.NUMERIC,
        help_text="How the metric value is formatted in the UI. One of `numeric` or `currency`.",
    )
    interval = serializers.IntegerField(
        default=7,
        help_text="Rolling time window in days used to compute the metric. Defaults to 7.",
    )
    display = serializers.ChoiceField(
        choices=GroupUsageMetric.Display.choices,
        default=GroupUsageMetric.Display.NUMBER,
        help_text="Visual representation in the UI. One of `number` or `sparkline`.",
    )
    filters = serializers.DictField(
        help_text=(
            "Filter definition for the metric. Two shapes are accepted, discriminated by an optional "
            "`source` key.\n\n"
            '**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — '
            "`events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n"
            '**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), '
            "`timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value "
            "matches the entity key). Currently DW metrics only render on group profiles — person profiles "
            "are not yet supported."
        ),
    )
    math = serializers.ChoiceField(
        choices=GroupUsageMetric.Math.choices,
        default=GroupUsageMetric.Math.COUNT,
        help_text=(
            "Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` "
            "on matching events."
        ),
    )
    math_property = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this "
            "is an event property name. For data warehouse metrics this is the column name (or HogQL "
            "expression) to sum on the DW table."
        ),
    )

    class Meta:
        model = GroupUsageMetric
        fields = ("id", "name", "format", "interval", "display", "filters", "math", "math_property")

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        data = super().validate(data)

        math = data.get("math", self.instance.math if self.instance else GroupUsageMetric.Math.COUNT)
        math_property = data.get("math_property", self.instance.math_property if self.instance else None)
        filters = data.get("filters", self.instance.filters if self.instance else None)

        source = (filters or {}).get("source") if isinstance(filters, dict) else None

        if source == GroupUsageMetric.Source.DATA_WAREHOUSE:
            self._validate_data_warehouse(cast(dict, filters), math, math_property)
        elif source in (None, GroupUsageMetric.Source.EVENTS):
            self._validate_events(math, math_property)
        else:
            raise serializers.ValidationError({"filters": f"Unknown source: {source!r}"})

        if "name" in data:
            self._validate_unique_name(data["name"])
        if source != GroupUsageMetric.Source.DATA_WAREHOUSE and "filters" in data:
            self._validate_cohort_filters(cast(dict, filters))

        return data

    def _validate_unique_name(self, name: str) -> None:
        group_type_index = self.instance.group_type_index if self.instance else self.context["group_type_index"]
        existing = GroupUsageMetric.objects.filter(
            team=self.context["get_team"](), group_type_index=group_type_index, name=name
        )
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError({"name": f"A usage metric named {name!r} already exists."})

    def _validate_cohort_filters(self, filters: dict) -> None:
        metric = GroupUsageMetric(team=self.context["get_team"](), filters=filters)
        reasons = metric.get_cohort_filter_errors()
        if reasons:
            raise serializers.ValidationError(
                {
                    "filters": (
                        f"Your internal and test account filters use cohorts that usage metrics can't use: "
                        f"{'; '.join(reasons)}. Use a cohort with only person property filters, "
                        f"or turn off the internal and test account filter for this metric."
                    )
                }
            )

    def _validate_events(self, math: str, math_property: str | None) -> None:
        if math == GroupUsageMetric.Math.SUM and not math_property:
            raise serializers.ValidationError({"math_property": "math_property is required when math is 'sum'."})
        if math == GroupUsageMetric.Math.COUNT and math_property:
            raise serializers.ValidationError({"math_property": "math_property must be empty when math is 'count'."})

    def _validate_data_warehouse(self, filters: dict, math: str, math_property: str | None) -> None:
        missing = [field for field in _DW_FILTER_REQUIRED_FIELDS if not filters.get(field)]
        if missing:
            raise serializers.ValidationError(
                {"filters": f"Data warehouse metrics require {', '.join(_DW_FILTER_REQUIRED_FIELDS)}."}
            )

        if math == GroupUsageMetric.Math.SUM and not math_property:
            raise serializers.ValidationError(
                {"math_property": "math_property (column to sum) is required when math is 'sum'."}
            )
        if math == GroupUsageMetric.Math.COUNT and math_property:
            raise serializers.ValidationError({"math_property": "math_property must be empty when math is 'count'."})

        team = self.context["get_team"]()
        if not DataWarehouseTable.objects.filter(team=team, name=filters["table_name"]).exclude(deleted=True).exists():
            raise serializers.ValidationError(
                {"filters": f"Data warehouse table {filters['table_name']!r} does not exist."}
            )


class GroupUsageMetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "usage_metric"
    queryset = GroupUsageMetric.objects.all()
    serializer_class = GroupUsageMetricSerializer

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(team=self.team, group_type_index=self.parents_query_dict["group_type_index"])
