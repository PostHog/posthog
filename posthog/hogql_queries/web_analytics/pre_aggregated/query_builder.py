from typing import Optional
from datetime import datetime, UTC

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

        # Only work for fixed-dates that don't include current-date in the filters while we test the pre-aggregated tables
        today = datetime.now(UTC).date()
        if self.runner.query_date_range.date_to().date() >= today:
            return False

        return True

    def _get_filters(self, table_name: str):
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[table_name, "period_bucket"]),
                right=ast.Constant(
                    value=(
                        self.runner.query_compare_to_date_range.date_from()
                        if self.runner.query_compare_to_date_range
                        else self.runner.query_date_range.date_from()
                    )
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=[table_name, "period_bucket"]),
                right=ast.Constant(value=self.runner.query_date_range.date_to()),
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

        # Create the field reference for period_bucket
        period_bucket_field = ast.Field(chain=[table_name, "period_bucket"] if table_name else ["period_bucket"])

        current_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=current_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=current_date_to),
                ),
            ]
        )

        previous_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=previous_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=previous_date_to),
                ),
            ]
        )

        return (previous_period_filter, current_period_filter)
