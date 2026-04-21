from collections.abc import Sequence
from typing import Any, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownFilter, BreakdownType, FunnelsQuery, LifecycleQuery, StickinessQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.resolver import resolve_types_from_table

from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node, is_data_warehouse_node
from posthog.hogql_queries.insights.utils.properties import has_any_property_filters
from posthog.hogql_queries.validation.utils import get_query_insight_name
from posthog.hogql_queries.validation.validation import QueryValidationContext
from posthog.models import Team


class RequireAtLeastOneSeries:
    """Insights need at least one series entity."""

    code = "insight_requires_at_least_one_series"

    def validate(self, context: QueryValidationContext[TrendsQuery | StickinessQuery | LifecycleQuery]) -> None:
        if not context.query.series:
            raise ValidationError(
                f"{get_query_insight_name(context.query)} require at least one series.",
                code=self.code,
            )


class DisallowUnsupportedDataWarehouseSettings:
    """Global property filters, test account filters and sampling can't be used together with data warehouse series."""

    code = "data_warehouse_series_unsupported_settings"

    def validate(
        self, context: QueryValidationContext[TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery]
    ) -> None:
        if not has_data_warehouse_node(context.query.series):
            return

        unsupported_settings: list[str] = []
        if has_any_property_filters(context.query.properties):
            unsupported_settings.append("filters")
        if context.query.filterTestAccounts:
            unsupported_settings.append("test account filters")
        if context.query.samplingFactor is not None:
            unsupported_settings.append("sampling")

        if unsupported_settings:
            settings = " and ".join(unsupported_settings)
            verb = "is" if unsupported_settings == ["sampling"] else "are"
            raise ValidationError(
                f"{settings.capitalize()} {verb} not supported for {get_query_insight_name(context.query).lower()} with a data warehouse series.",
                code=self.code,
            )


VALID_DATA_WAREHOUSE_BREAKDOWN_CONSTANT_TYPES = (
    ast.BooleanType,
    ast.DateType,
    ast.DateTimeType,
    ast.DecimalType,
    ast.FloatType,
    ast.IntegerType,
    ast.StringType,
)


def get_data_warehouse_breakdown_error(
    team: Team,
    series: Sequence[Any] | None,
    breakdown_filter: BreakdownFilter | None,
) -> str | None:
    if not series or not breakdown_filter:
        return None

    data_warehouse_series = [node for node in series if is_data_warehouse_node(node)]
    if not data_warehouse_series:
        return None

    has_non_data_warehouse_series = len(data_warehouse_series) != len(series)

    if has_non_data_warehouse_series and breakdown_filter.breakdown_type != BreakdownType.DATA_WAREHOUSE:
        return None

    if breakdown_filter.breakdowns:
        return "Insights with a data warehouse series can only be broken down by a single data warehouse property."

    breakdown_value = breakdown_filter.breakdown
    if isinstance(breakdown_value, list):
        if len(breakdown_value) != 1 or not isinstance(breakdown_value[0], str):
            return "Insights with a data warehouse series can only be broken down by a single data warehouse property."
        breakdown_value = breakdown_value[0]

    if breakdown_filter.breakdown_type != BreakdownType.DATA_WAREHOUSE or not isinstance(breakdown_value, str):
        return "Insights with a data warehouse series can only be broken down by a single data warehouse property."

    breakdown_field = breakdown_value
    database = Database.create_for(team=team)
    context = HogQLContext(team_id=team.pk, team=team, database=database)

    breakdown_field_chain = cast(list[str | int], breakdown_field.split("."))

    for node in data_warehouse_series:
        try:
            resolved_expr = resolve_types_from_table(
                ast.Field(chain=breakdown_field_chain),
                [node.table_name],
                context,
                "hogql",
            )
        except QueryError:
            return f'"{breakdown_field}" is not a valid data warehouse property for breakdowns.'

        resolved_type = resolved_expr.type.resolve_constant_type(context) if resolved_expr.type is not None else None
        if type(resolved_type) not in VALID_DATA_WAREHOUSE_BREAKDOWN_CONSTANT_TYPES:
            return f'"{breakdown_field}" is not a valid data warehouse property for breakdowns.'

    return None


class ValidateDataWarehouseBreakdown:
    """Multi-propert breakdowns and event based breakdown types can't be used together with data warehouse series."""

    code = "data_warehouse_series_unsupported_breakdown"

    def validate(self, context: QueryValidationContext[TrendsQuery | FunnelsQuery]) -> None:
        if not has_data_warehouse_node(context.query.series):
            return

        if not context.query.breakdownFilter:
            return

        context.query.breakdownFilter

    #     class BreakdownFilter(BaseModel):
    # model_config = ConfigDict(
    #     extra="forbid",
    # )
    # breakdown: str | list[str | int] | int | None = None
    # breakdown_group_type_index: int | None = None
    # breakdown_hide_other_aggregation: bool | None = None
    # breakdown_histogram_bin_count: int | None = None
    # breakdown_limit: int | None = None
    # breakdown_normalize_url: bool | None = None
    # breakdown_path_cleaning: bool | None = None
    # breakdown_type: BreakdownType | None = BreakdownType.EVENT
    # breakdowns: list[Breakdown] | None = Field(default=None, max_length=3)

    # unsupported_settings: list[str] = []
    # if has_any_property_filters(context.query.properties):
    #     unsupported_settings.append("filters")
    # if context.query.filterTestAccounts:
    #     unsupported_settings.append("test account filters")
    # if context.query.samplingFactor is not None:
    #     unsupported_settings.append("sampling")

    # if unsupported_settings:
    #     settings = " and ".join(unsupported_settings)
    #     verb = "is" if unsupported_settings == ["sampling"] else "are"
    #     raise ValidationError(
    #         f"{settings.capitalize()} {verb} not supported for {get_query_insight_name(context.query).lower()} with a data warehouse series.",
    #         code=self.code,
    #     )
