from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.pre_aggregated.date_range import WebAnalyticsPreAggregatedDateRange
from posthog.hogql_queries.web_analytics.pre_aggregated.property_transformer import (
    ChannelTypeReplacer,
    PreAggregatedPropertyTransformer,
)
from posthog.hogql_queries.web_analytics.pre_aggregated.utils import get_bounces_table, get_stats_table


class WebAnalyticsPreAggregatedQueryBuilder:
    def __init__(self, runner, supported_props_filters) -> None:
        self.runner = runner
        self.supported_props_filters = supported_props_filters

    @property
    def stats_table(self) -> str:
        return get_stats_table(self.runner.use_v2_tables)

    @property
    def bounces_table(self) -> str:
        return get_bounces_table(self.runner.use_v2_tables)

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.supported_props_filters:
                return False

        if query.conversionGoal:
            return False

        if not self.can_use_date_range():
            return False

        return True

    def can_use_date_range(self) -> bool:
        # Parse the query's requested date range
        # Some queries (like WebOverviewQuery) don't have an interval property, so we default to None
        interval = getattr(self.runner.query, "interval", None)
        requested_date_range = QueryDateRange(
            date_range=self.runner.query.dateRange,
            team=self.runner.team,
            interval=interval,
            now=datetime.now(),
        )

        requested_start = requested_date_range.date_from()
        requested_end = requested_date_range.date_to()

        # Convert requested dates to UTC for comparison with table data (which is stored in UTC)
        if hasattr(requested_start, "astimezone"):
            requested_start_utc = requested_start.astimezone(ZoneInfo("UTC"))
            requested_end_utc = requested_end.astimezone(ZoneInfo("UTC"))
        else:
            # If dates are already timezone-naive, assume they're UTC
            requested_start_utc = requested_start
            requested_end_utc = requested_end

        # Check if the requested range is available in pre-aggregated tables
        use_v2_tables = getattr(self.runner, "use_v2_tables", False)
        date_range_checker = WebAnalyticsPreAggregatedDateRange(team=self.runner.team, use_v2_tables=use_v2_tables)

        return date_range_checker.is_date_range_pre_aggregated(requested_start_utc, requested_end_utc)

    def _get_channel_type_expr(self) -> ast.Expr:
        def _wrap_with_null_if_empty(expr: ast.Expr) -> ast.Expr:
            return ast.Call(
                name="nullIf",
                args=[ast.Call(name="nullIf", args=[expr, ast.Constant(value="")]), ast.Constant(value="null")],
            )

        def _wrap_with_lower(expr: ast.Expr) -> ast.Expr:
            return ast.Call(name="lower", args=[expr])

        channel_type_exprs = ChannelTypeExprs(
            campaign=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_campaign"]))),
            medium=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_medium"]))),
            source=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_source"]))),
            referring_domain=_wrap_with_null_if_empty(ast.Field(chain=["referring_domain"])),
            url=ast.Constant(value=None),  # URL not available in pre-aggregated tables
            hostname=ast.Field(chain=["host"]),
            pathname=ast.Field(chain=["entry_pathname"]),
            has_gclid=ast.Field(chain=["has_gclid"]),
            has_fbclid=ast.Field(chain=["has_fbclid"]),
            # To keep this compatible with the non-pre-aggregated version, we need to return '1' when the boolean is true, null otherwise
            gad_source=ast.Call(
                name="if",
                args=[
                    ast.Field(chain=["has_gad_source_paid_search"]),
                    ast.Constant(value="1"),
                    ast.Constant(value=None),
                ],
            ),
        )

        return create_channel_type_expr(
            custom_rules=None,  # Custom rules not supported for pre-aggregated tables yet
            source_exprs=channel_type_exprs,
            timings=self.runner.timings,
        )

    def _get_filters(self, table_name: str, exclude_pathname: bool = False):
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
            virtual_properties = []
            regular_properties = []

            for prop in self.runner.query.properties:
                if hasattr(prop, "key") and prop.key in self.supported_props_filters:
                    if exclude_pathname and prop.key == "$pathname":
                        continue
                    if self.supported_props_filters[prop.key] is None:
                        virtual_properties.append(prop)
                    else:
                        regular_properties.append(prop)

            if regular_properties:
                property_expr = property_to_expr(regular_properties, self.runner.team)
                transformer = PreAggregatedPropertyTransformer(table_name, self.supported_props_filters)
                transformed_expr = transformer.visit(property_expr)
                filter_exprs.append(transformed_expr)

            if virtual_properties:
                for prop in virtual_properties:
                    if prop.key == "$channel_type":
                        replacer = ChannelTypeReplacer(self._get_channel_type_expr())
                        filter_exprs.append(replacer.visit(property_to_expr([prop], self.runner.team)))

        return ast.And(exprs=filter_exprs)

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
