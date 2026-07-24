from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownType, MultipleBreakdownType, PropertyMathType, TrendsQuery

from posthog.hogql_queries.insights.trends.aggregation_operations import SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN
from posthog.hogql_queries.insights.utils.breakdowns import (
    has_breakdown_filter,
    has_multi_breakdown,
    has_single_breakdown,
)
from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node
from posthog.hogql_queries.validation.utils import get_query_insight_name
from posthog.hogql_queries.validation.validation import QueryValidationContext


class ValidateDataWarehouseBreakdown:
    """Event based breakdown types can't be used together with data warehouse series."""

    code = "data_warehouse_series_unsupported_breakdown"

    def validate(self, context: QueryValidationContext[TrendsQuery]) -> None:
        if not has_data_warehouse_node(context.query.series):
            return

        if not has_breakdown_filter(context.query.breakdownFilter):
            return

        assert context.query.breakdownFilter is not None  # type checking
        breakdown_filter = context.query.breakdownFilter
        insight_name = get_query_insight_name(context.query).lower()

        # `hogql` breakdowns resolve against the FROM clause, which for a `DataWarehouseNode`
        # series is the warehouse table itself — so they're safe alongside `data_warehouse`.
        supported_multi_types = {MultipleBreakdownType.DATA_WAREHOUSE, MultipleBreakdownType.HOGQL}
        supported_single_types = {BreakdownType.DATA_WAREHOUSE, BreakdownType.HOGQL}

        if has_multi_breakdown(breakdown_filter):
            assert breakdown_filter.breakdowns is not None  # type checking
            if any(breakdown.type not in supported_multi_types for breakdown in breakdown_filter.breakdowns):
                raise ValidationError(
                    f"Event based breakdowns are not supported for {insight_name} with a data warehouse series.",
                    code=self.code,
                )
            return

        if has_single_breakdown(breakdown_filter) and breakdown_filter.breakdown_type not in supported_single_types:
            raise ValidationError(
                f"Event based breakdowns are not supported for {insight_name} with a data warehouse series.",
                code=self.code,
            )


class DisallowUnsupportedPropertyMathForHistogramBreakdown:
    """Median and percentile property math can't be merged when rolling up histogram breakdown buckets."""

    code = "property_math_unsupported_with_histogram_breakdown"

    def validate(self, context: QueryValidationContext[TrendsQuery]) -> None:
        breakdown_filter = context.query.breakdownFilter
        if not has_breakdown_filter(breakdown_filter):
            return
        assert breakdown_filter is not None  # type checking

        if has_multi_breakdown(breakdown_filter):
            assert breakdown_filter.breakdowns is not None  # type checking
            has_histogram = any(breakdown.histogram_bin_count is not None for breakdown in breakdown_filter.breakdowns)
        else:
            has_histogram = breakdown_filter.breakdown_histogram_bin_count is not None
        if not has_histogram:
            return

        unsupported_math_types = sorted(
            {
                PropertyMathType(series.math)
                for series in context.query.series
                if series.math in set(PropertyMathType)
                and series.math not in SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN
            }
        )
        if not unsupported_math_types:
            return

        names = " and ".join(unsupported_math_types)
        verb = "is" if len(unsupported_math_types) == 1 else "are"
        raise ValidationError(
            f"{names.capitalize()} {verb} not supported when breakdown values are grouped into bins. "
            "Use average instead, or turn off binning on the breakdown.",
            code=self.code,
        )


class DisallowDaysOfWeekWithSmoothing:
    """Smoothing averages over the full date axis, where days excluded by daysOfWeek are structural zeros."""

    code = "days_of_week_unsupported_with_smoothing"

    def validate(self, context: QueryValidationContext[TrendsQuery]) -> None:
        query = context.query
        trends_filter = query.trendsFilter
        if trends_filter is None or trends_filter.smoothingIntervals is None or trends_filter.smoothingIntervals <= 1:
            return

        days = set(query.dateRange.daysOfWeek or []) if query.dateRange else set()
        if days and len(days) < 7:
            raise ValidationError(
                "Smoothing is not supported together with a days-of-week restriction: "
                "the rolling average would count the excluded days as zeros and understate every value. "
                "Remove smoothing or the daysOfWeek filter.",
                code=self.code,
            )
