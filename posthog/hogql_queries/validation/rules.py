from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelsQuery, LifecycleQuery, StickinessQuery, TrendsQuery

from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node
from posthog.hogql_queries.insights.utils.properties import has_any_property_filters
from posthog.hogql_queries.validation.utils import get_query_insight_name
from posthog.hogql_queries.validation.validation import QueryValidationContext


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
