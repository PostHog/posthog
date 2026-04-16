from rest_framework.exceptions import ValidationError

from posthog.schema import LifecycleQuery

from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node
from posthog.hogql_queries.validation.validation import QueryValidationContext


class RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget:
    def validate(self, context: QueryValidationContext[LifecycleQuery]) -> None:
        if not context.query.customAggregationTarget:
            return

        if has_data_warehouse_node(context.query.series):
            return

        raise ValidationError(
            "Custom entity aggregation target is not supported for lifecycle insights without a data warehouse series."
        )
