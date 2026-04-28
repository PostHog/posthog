from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownType, MultipleBreakdownType, TrendsQuery

from posthog.hogql_queries.insights.utils.breakdowns import (
    has_breakdown_filter,
    has_multi_breakdown,
    has_single_breakdown,
)
from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node
from posthog.hogql_queries.validation.utils import get_query_insight_name
from posthog.hogql_queries.validation.validation import QueryValidationContext


class ValidateDataWarehouseBreakdown:
    """Multi-property breakdowns and event based breakdown types can't be used together with data warehouse series."""

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
            if len(breakdown_filter.breakdowns) > 1:
                raise ValidationError(
                    f"Multi-breakdowns not supported for {insight_name} with a data warehouse series.",
                    code=self.code,
                )

            if breakdown_filter.breakdowns[0].type not in supported_multi_types:
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
