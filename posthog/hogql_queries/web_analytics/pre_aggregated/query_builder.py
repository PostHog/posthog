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

        # Now we can support current day queries using UNION ALL with hourly tables
        return True

    def _includes_current_day(self) -> bool:
        """Check if the query date range includes the current day."""
        today = datetime.now(UTC).date()
        return self.runner.query_date_range.date_to().date() >= today

    def _get_current_day_start(self) -> datetime:
        """Get the start of the current day in UTC."""
        today = datetime.now(UTC).date()
        return datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)

    def _get_filters(self, table_name: str, granularity: str = "daily"):
        bucket_column = "hour_bucket" if granularity == "hourly" else "day_bucket"
        
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[table_name, bucket_column]),
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
                left=ast.Field(chain=[table_name, bucket_column]),
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

    def _get_filters_for_daily_part(self, table_name: str):
        """Get filters for the daily table part of UNION ALL - excludes current day."""
        current_day_start = self._get_current_day_start()
        
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[table_name, "day_bucket"]),
                right=ast.Constant(
                    value=(
                        self.runner.query_compare_to_date_range.date_from()
                        if self.runner.query_compare_to_date_range
                        else self.runner.query_date_range.date_from()
                    )
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=[table_name, "day_bucket"]),
                right=ast.Constant(value=current_day_start),
            ),
        ]

        # Add team filter
        filter_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[table_name, "team_id"]),
                right=ast.Constant(value=self.runner.team.pk),
            )
        )

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

    def _get_filters_for_hourly_part(self, table_name: str):
        """Get filters for the hourly table part of UNION ALL - only current day."""
        current_day_start = self._get_current_day_start()
        
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[table_name, "hour_bucket"]),
                right=ast.Constant(value=current_day_start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=[table_name, "hour_bucket"]),
                right=ast.Constant(value=self.runner.query_date_range.date_to()),
            ),
        ]

        # Add team filter  
        filter_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[table_name, "team_id"]),
                right=ast.Constant(value=self.runner.team.pk),
            )
        )

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

    def get_date_ranges(self, table_name: Optional[str] = None, granularity: str = "daily") -> tuple[ast.Expr, ast.Expr]:
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

        # Create the field reference for the appropriate bucket
        bucket_column = "hour_bucket" if granularity == "hourly" else "day_bucket"
        bucket_field = ast.Field(chain=[table_name, bucket_column] if table_name else [bucket_column])

        current_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=bucket_field,
                    right=ast.Constant(value=current_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=bucket_field,
                    right=ast.Constant(value=current_date_to),
                ),
            ]
        )

        previous_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=bucket_field,
                    right=ast.Constant(value=previous_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=bucket_field,
                    right=ast.Constant(value=previous_date_to),
                ),
            ]
        )

        return (previous_period_filter, current_period_filter)

    def get_date_ranges_for_union(self, table_name: Optional[str] = None, granularity: str = "daily") -> tuple[ast.Expr, ast.Expr]:
        """Get date ranges for UNION ALL parts - handles splitting current day logic."""
        current_date_from = self.runner.query_date_range.date_from()
        current_date_to = self.runner.query_date_range.date_to()
        current_day_start = self._get_current_day_start()

        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from()
            previous_date_to = self.runner.query_compare_to_date_range.date_to()
        else:
            previous_date_from = current_date_from
            previous_date_to = current_date_to

        bucket_column = "hour_bucket" if granularity == "hourly" else "day_bucket"
        bucket_field = ast.Field(chain=[table_name, bucket_column] if table_name else [bucket_column])

        if granularity == "hourly":
            # For hourly part: only current day data
            current_period_filter = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=bucket_field,
                        right=ast.Constant(value=current_day_start),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=bucket_field,
                        right=ast.Constant(value=current_date_to),
                    ),
                ]
            )

            # For previous period in hourly: if it includes current day, use current day start, else use original range  
            if previous_date_to >= current_day_start:
                previous_period_filter = ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=bucket_field,
                            right=ast.Constant(value=max(previous_date_from, current_day_start)),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=bucket_field,
                            right=ast.Constant(value=previous_date_to),
                        ),
                    ]
                )
            else:
                # Previous period doesn't include current day, so no data from hourly table
                previous_period_filter = ast.Constant(value=False)

        else:
            # For daily part: exclude current day
            current_period_filter = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=bucket_field,
                        right=ast.Constant(value=current_date_from),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=bucket_field,
                        right=ast.Constant(value=current_day_start),
                    ),
                ]
            )

            previous_period_filter = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=bucket_field,
                        right=ast.Constant(value=previous_date_from),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=bucket_field,
                        right=ast.Constant(value=current_day_start),
                    ),
                ]
            )

        return (previous_period_filter, current_period_filter)
