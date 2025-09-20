from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, EventsNode, FunnelsFilter, FunnelsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.funnel_aggregation_operations import FirstTimeForUserAggregationQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext


class TestFunnelAggregationOperations(ClickhouseTestMixin, APIBaseTest):
    def test_first_time_for_user_aggregation_outer_query(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )
        ctx = FunnelQueryContext(funnels_query, self.team)
        filters = parse_expr("1 = 1")
        event_filter = parse_expr("2 = 2")

        builder = FirstTimeForUserAggregationQuery(context=ctx, filters=filters, event_or_action_filter=event_filter)
        query = builder.to_query()

        assert isinstance(query.select[0], ast.Field)
        assert query.select[0].chain == ["uuid"]
        assert query.select_from is not None
        assert isinstance(query.select_from.table, ast.SelectQuery)

    def test_first_time_for_user_aggregation_query_select(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )

        with freeze_time("2024-07-31"):
            ctx = FunnelQueryContext(funnels_query, self.team)
            filters = parse_expr("1 = 1")
            event_filter = parse_expr("2 = 2")

            builder = FirstTimeForUserAggregationQuery(
                context=ctx, filters=filters, event_or_action_filter=event_filter
            )
            query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        first = query.select[0]
        assert isinstance(first, ast.Alias)
        assert first.alias == "min_timestamp"
        assert isinstance(first.expr, ast.Call)
        assert first.expr.name == "min"
        assert isinstance(first.expr.args[0], ast.Field)
        assert first.expr.args[0].chain == ["timestamp"]

        second = query.select[1]
        assert isinstance(second, ast.Alias)
        assert second.alias == "min_timestamp_with_condition"
        assert isinstance(second.expr, ast.Call)
        assert second.expr.name == "minIf"
        assert isinstance(second.expr.args[0], ast.Field)
        assert second.expr.args[0].chain == ["timestamp"]
        assert isinstance(second.expr.args[1], ast.And)
        assert len(second.expr.args[1].exprs) == 2
        assert isinstance(second.expr.args[1].exprs[0], ast.CompareOperation)
        date_from = second.expr.args[1].exprs[0].right
        assert isinstance(date_from, ast.Constant)
        assert date_from.value == datetime(2024, 7, 17, tzinfo=ZoneInfo(key="UTC"))
        assert second.expr.args[1].exprs[1] == filters

        third = query.select[2]
        assert isinstance(third, ast.Alias)
        assert third.alias == "uuid"
        assert isinstance(third.expr, ast.Call)
        assert third.expr.name == "argMin"
        assert isinstance(third.expr.args[0], ast.Field)
        assert third.expr.args[0].chain == ["uuid"]
        assert isinstance(third.expr.args[1], ast.Field)
        assert third.expr.args[1].chain == ["timestamp"]

    def test_first_time_for_user_aggregation_query_filter(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )

        with freeze_time("2024-07-31"):
            ctx = FunnelQueryContext(funnels_query, self.team)
            filters = parse_expr("1 = 1")
            event_filter = parse_expr("2 = 2")

            builder = FirstTimeForUserAggregationQuery(
                context=ctx, filters=filters, event_or_action_filter=event_filter
            )
            query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        assert isinstance(query.where, ast.And)
        assert isinstance(query.where.exprs[0], ast.CompareOperation)
        date_from = query.where.exprs[0].right
        assert isinstance(date_from, ast.Constant)
        assert date_from.value == datetime(2024, 7, 31, 23, 59, 59, 999999, tzinfo=ZoneInfo(key="UTC"))
        assert query.where.exprs[1] == event_filter

    def test_first_time_for_user_aggregation_query_no_filters(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )

        with freeze_time("2024-07-31"):
            ctx = FunnelQueryContext(funnels_query, self.team)
            builder = FirstTimeForUserAggregationQuery(context=ctx)
            query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        second = query.select[1]
        assert isinstance(second, ast.Alias)
        assert isinstance(second.expr, ast.Call)
        assert isinstance(second.expr.args[1], ast.CompareOperation)
        date_from = second.expr.args[1].right
        assert isinstance(date_from, ast.Constant)
        assert date_from.value == datetime(2024, 7, 17, tzinfo=ZoneInfo(key="UTC"))

        assert isinstance(query.where, ast.CompareOperation)
        date_from = query.where.right
        assert isinstance(date_from, ast.Constant)
        assert date_from.value == datetime(2024, 7, 31, 23, 59, 59, 999999, tzinfo=ZoneInfo(key="UTC"))

    def test_first_time_for_user_aggregation_query_group_by(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )
        ctx = FunnelQueryContext(funnels_query, self.team)

        builder = FirstTimeForUserAggregationQuery(context=ctx)
        query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        assert query.group_by is not None
        assert isinstance(query.group_by[0], ast.Field)
        assert query.group_by[0].chain == ["person_id"]

    def test_first_time_for_user_aggregation_query_having(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )
        ctx = FunnelQueryContext(funnels_query, self.team)

        builder = FirstTimeForUserAggregationQuery(context=ctx)
        query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        assert query.having is not None
        assert isinstance(query.having, ast.And)

        assert len(query.having.exprs) == 2

        first = query.having.exprs[0]
        assert isinstance(first, ast.CompareOperation)
        assert first.op == ast.CompareOperationOp.Eq
        assert isinstance(first.left, ast.Field)
        assert first.left.chain == ["min_timestamp"]
        assert isinstance(first.right, ast.Field)
        assert first.right.chain == ["min_timestamp_with_condition"]

        second = query.having.exprs[1]
        assert isinstance(second, ast.CompareOperation)
        assert second.op == ast.CompareOperationOp.NotEq
        assert isinstance(second.left, ast.Field)
        assert second.left.chain == ["min_timestamp"]
        assert isinstance(second.right, ast.Call)

    def test_first_time_for_user_aggregation_query_sampling_factor(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
            samplingFactor=0.1,
        )
        ctx = FunnelQueryContext(funnels_query, self.team)

        builder = FirstTimeForUserAggregationQuery(context=ctx)
        query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        assert query.select_from is not None
        assert query.select_from.sample is not None
        assert query.select_from.sample.sample_value == ast.RatioExpr(left=ast.Constant(value=0.1))

    def test_first_time_for_user_aggregation_query_select_from(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview")],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=14),
            dateRange=DateRange(date_from="-14d"),
        )
        ctx = FunnelQueryContext(funnels_query, self.team)

        builder = FirstTimeForUserAggregationQuery(context=ctx)
        query = builder.to_query()

        assert query.select_from is not None
        query = cast(ast.SelectQuery, query.select_from.table)

        assert query.select_from is not None
        assert query.select_from.sample is None
        assert isinstance(query.select_from.table, ast.Field)
        assert query.select_from.table.chain == ["events"]
