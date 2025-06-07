from typing import Optional
from datetime import UTC

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.web_analytics.pre_aggregated.property_transformer import PreAggregatedPropertyTransformer


class WebAnalyticsPreAggregatedQueryBuilder:
    def __init__(self, runner, supported_props_filters) -> None:
        self.runner = runner
        self.supported_props_filters = supported_props_filters

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.supported_props_filters:
                return False

        if query.conversionGoal:
            return False

        return True

    def _datetime_to_utc_hogql(self, dt) -> ast.Call:
        utc_dt = dt.astimezone(UTC)
        return ast.Call(name="toDateTime", args=[ast.Constant(value=utc_dt.strftime("%Y-%m-%d %H:%M:%S"))])

    def _period_bucket_field_utc(self, table_name: Optional[str] = None) -> ast.Call:
        field = ast.Field(chain=[table_name, "period_bucket"] if table_name else ["period_bucket"])
        # Explicitly wrap in toDateTime with UTC to make UTC usage clear
        return ast.Call(name="toDateTime", args=[field, ast.Constant(value="UTC")])

    def _get_filters(self, table_name: str):
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=self._period_bucket_field_utc(table_name),
                right=self._datetime_to_utc_hogql(
                    self.runner.query_compare_to_date_range.date_from()
                    if self.runner.query_compare_to_date_range
                    else self.runner.query_date_range.date_from()
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=self._period_bucket_field_utc(table_name),
                right=self._datetime_to_utc_hogql(self.runner.query_date_range.date_to()),
            ),
        ]

        if self.runner.query.properties:
            supported_properties = [
                prop
                for prop in self.runner.query.properties
                if hasattr(prop, "key") and prop.key in self.supported_props_filters
            ]

            if supported_properties:
                property_expr = property_to_expr(supported_properties, self.runner.team)

                transformer = PreAggregatedPropertyTransformer(table_name, self.supported_props_filters)
                transformed_expr = transformer.visit(property_expr)

                filter_exprs.append(transformed_expr)

        return ast.And(exprs=filter_exprs) if len(filter_exprs) > 1 else filter_exprs[0]

    def get_date_ranges(self, table_name: Optional[str] = None) -> tuple[ast.Expr, ast.Expr]:
        current_date_from = self.runner.query_date_range.date_from()
        current_date_to = self.runner.query_date_range.date_to()

        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from()
            previous_date_to = self.runner.query_compare_to_date_range.date_to()
        else:
            # If we don't have a previous period, we can just use the same data as the values won't be used
            # and our query stays simpler.
            previous_date_from = current_date_from
            previous_date_to = current_date_to

        # Create the field reference for period_bucket with explicit UTC
        period_bucket_field = self._period_bucket_field_utc(table_name)

        current_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=self._datetime_to_utc_hogql(current_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=self._datetime_to_utc_hogql(current_date_to),
                ),
            ]
        )

        previous_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=self._datetime_to_utc_hogql(previous_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=self._datetime_to_utc_hogql(previous_date_to),
                ),
            ]
        )

        return (previous_period_filter, current_period_filter)
