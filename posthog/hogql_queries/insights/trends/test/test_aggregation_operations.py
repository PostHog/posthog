from datetime import datetime
from typing import Literal, Union, cast

import pytest

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
    FirstTimeForUserEventsQueryAlternator,
    QueryAlternator,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    CountPerActorMathType,
    EventsNode,
    PropertyMathType,
)


class TestQueryAlternator:
    def test_select(self):
        query = cast(ast.SelectQuery, parse_select("SELECT event from events"))

        query_modifier = QueryAlternator(query)
        query_modifier.append_select(ast.Field(chain=["test"]))
        query_modifier.build()

        assert len(query.select) == 2
        assert cast(ast.Field, query.select[1]).chain == ["test"]

        query = cast(ast.SelectQuery, parse_select("SELECT event from events"))

        query_modifier = QueryAlternator(query)
        query_modifier.extend_select([ast.Field(chain=["test1"]), ast.Field(chain=["test2"])])
        query_modifier.build()

        assert len(query.select) == 3
        assert cast(ast.Field, query.select[1]).chain == ["test1"]
        assert cast(ast.Field, query.select[2]).chain == ["test2"]

    def test_group_no_pre_existing(self):
        query = cast(ast.SelectQuery, parse_select("SELECT event from events"))

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert query.group_by is not None
        assert len(query.group_by) == 1
        assert cast(ast.Field, query.group_by[0]).chain == ["event"]

    def test_group_with_pre_existing(self):
        query = cast(ast.SelectQuery, parse_select("SELECT event from events GROUP BY uuid"))

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert query.group_by is not None
        assert len(query.group_by) == 2
        assert cast(ast.Field, query.group_by[0]).chain == ["uuid"]
        assert cast(ast.Field, query.group_by[1]).chain == ["event"]

    def test_replace_select_from(self):
        query = cast(ast.SelectQuery, parse_select("SELECT event from events"))

        query_modifier = QueryAlternator(query)
        query_modifier.replace_select_from(ast.JoinExpr(table=ast.Field(chain=["groups"])))
        query_modifier.build()

        assert isinstance(query.select_from, ast.JoinExpr)
        assert isinstance(query.select_from.table, ast.Field)
        assert query.select_from.table.chain == ["groups"]


@pytest.mark.parametrize(
    "math,math_property",
    [
        [BaseMathType.TOTAL, None],
        [BaseMathType.DAU, None],
        [BaseMathType.WEEKLY_ACTIVE, None],
        [BaseMathType.MONTHLY_ACTIVE, None],
        [BaseMathType.UNIQUE_SESSION, None],
        [BaseMathType.FIRST_TIME_FOR_USER, None],
        [PropertyMathType.AVG, "$browser"],
        [PropertyMathType.SUM, "$browser"],
        [PropertyMathType.MIN, "$browser"],
        [PropertyMathType.MAX, "$browser"],
        [PropertyMathType.MEDIAN, "$browser"],
        [PropertyMathType.P90, "$browser"],
        [PropertyMathType.P95, "$browser"],
        [PropertyMathType.P99, "$browser"],
        [CountPerActorMathType.AVG_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MIN_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MAX_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MEDIAN_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.P90_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.P95_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.P99_COUNT_PER_ACTOR, None],
        ["hogql", None],
    ],
)
@pytest.mark.django_db
def test_all_cases_return(
    math: Union[
        BaseMathType,
        PropertyMathType,
        CountPerActorMathType,
        Literal["unique_group"],
        Literal["hogql"],
    ],
    math_property: str,
):
    team = Team()
    series = EventsNode(event="$pageview", math=math, math_property=math_property)
    query_date_range = QueryDateRange(date_range=None, interval=None, now=datetime.now(), team=team)

    agg_ops = AggregationOperations(team, series, ChartDisplayType.ACTIONS_LINE_GRAPH, query_date_range, False)
    res = agg_ops.select_aggregation()
    assert isinstance(res, ast.Expr)


@pytest.mark.parametrize(
    "math,result",
    [
        [BaseMathType.TOTAL, False],
        [BaseMathType.DAU, False],
        [BaseMathType.WEEKLY_ACTIVE, True],
        [BaseMathType.MONTHLY_ACTIVE, True],
        [BaseMathType.UNIQUE_SESSION, False],
        [BaseMathType.FIRST_TIME_FOR_USER, True],
        [PropertyMathType.AVG, False],
        [PropertyMathType.SUM, False],
        [PropertyMathType.MIN, False],
        [PropertyMathType.MAX, False],
        [PropertyMathType.MEDIAN, False],
        [PropertyMathType.P90, False],
        [PropertyMathType.P95, False],
        [PropertyMathType.P99, False],
        [CountPerActorMathType.AVG_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MIN_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MAX_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MEDIAN_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.P90_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.P95_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.P99_COUNT_PER_ACTOR, True],
        ["hogql", False],
    ],
)
def test_requiring_query_orchestration(
    math: Union[
        BaseMathType,
        PropertyMathType,
        CountPerActorMathType,
        Literal["unique_group"],
        Literal["hogql"],
    ],
    result: bool,
):
    team = Team()
    series = EventsNode(event="$pageview", math=math)
    query_date_range = QueryDateRange(date_range=None, interval=None, now=datetime.now(), team=team)

    agg_ops = AggregationOperations(team, series, ChartDisplayType.ACTIONS_LINE_GRAPH, query_date_range, False)
    res = agg_ops.requires_query_orchestration()
    assert res == result


class TestFirstTimeForUserEventsQueryAlternator:
    def test_query(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to = parse_expr("1 = 1"), parse_expr("2 = 2")

        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to)
        builder.build()

        assert len(query.select) == 2

        assert isinstance(query.select[0], ast.Alias)
        assert query.select[0].alias == "min_timestamp"
        assert isinstance(query.select[0].expr, ast.Call)
        assert query.select[0].expr.name == "min"
        assert query.select[0].expr.args == [ast.Field(chain=["timestamp"])]

        assert isinstance(query.select[1], ast.Alias)
        assert query.select[1].alias == "min_timestamp_with_condition"
        assert isinstance(query.select[1].expr, ast.Call)
        assert query.select[1].expr.name == "minIf"
        assert query.select[1].expr.args == [ast.Field(chain=["timestamp"]), date_from]

        assert isinstance(query.select_from, ast.JoinExpr)
        assert query.select_from.alias == "e"
        assert isinstance(query.select_from.table, ast.Field)
        assert query.select_from.table.chain == ["events"]
        assert query.select_from.sample is None

        assert query.where == date_to

        assert isinstance(query.group_by, list)
        assert isinstance(query.group_by[0], ast.Field)
        assert query.group_by[0].chain == ["person_id"]

        assert isinstance(query.having, ast.CompareOperation)
        assert query.having.op == ast.CompareOperationOp.Eq
        assert isinstance(query.having.left, ast.Field)
        assert query.having.left.chain == ["min_timestamp"]
        assert isinstance(query.having.right, ast.Field)
        assert query.having.right.chain == ["min_timestamp_with_condition"]

    def test_query_with_filters(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to, filters = parse_expr("1 = 1"), parse_expr("2 = 2"), parse_expr("3 = 3")

        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to, filters=filters)
        builder.build()

        assert len(query.select) == 2

        assert isinstance(query.select[0], ast.Alias)
        assert query.select[0].alias == "min_timestamp"
        assert isinstance(query.select[0].expr, ast.Call)
        assert query.select[0].expr.name == "min"
        assert query.select[0].expr.args == [ast.Field(chain=["timestamp"])]

        assert isinstance(query.select[1], ast.Alias)
        assert query.select[1].alias == "min_timestamp_with_condition"
        assert isinstance(query.select[1].expr, ast.Call)
        assert query.select[1].expr.name == "minIf"
        assert query.select[1].expr.args == [ast.Field(chain=["timestamp"]), ast.And(exprs=[date_from, filters])]

    def test_query_with_event_or_action_filter(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to, event_filter = parse_expr("1 = 1"), parse_expr("2 = 2"), parse_expr("3 = 3")

        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to, event_or_action_filter=event_filter)
        builder.build()

        assert isinstance(query.where, ast.And)
        assert len(query.where.exprs) == 2
        assert query.where.exprs[0] == date_to
        assert query.where.exprs[1] == event_filter

    def test_query_with_ratio_expr(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to, ratio_expr = (
            parse_expr("1 = 1"),
            parse_expr("2 = 2"),
            ast.RatioExpr(left=ast.Constant(value=1)),
        )

        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to, ratio=ratio_expr)
        builder.build()

        assert isinstance(query.select_from, ast.JoinExpr)
        assert query.select_from.alias == "e"
        assert isinstance(query.select_from.table, ast.Field)
        assert query.select_from.table.chain == ["events"]
        assert isinstance(query.select_from.sample, ast.SampleExpr)
        assert query.select_from.sample.sample_value == ratio_expr

    def test_append_select(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to = parse_expr("1 = 1"), parse_expr("2 = 2")
        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to)

        builder.append_select(ast.Field(chain=["test"]))
        builder.append_select(ast.Alias(alias="test2", expr=ast.Field(chain=["test2"])))
        builder.append_select(ast.Field(chain=["test3"]), aggregate=True)
        builder.append_select(ast.Alias(alias="test4", expr=ast.Field(chain=["test4"])), aggregate=True)
        builder.build()

        assert len(query.select) == 6

        assert cast(ast.Field, query.select[2]).chain == ["test"]
        assert isinstance(query.select[3], ast.Alias)
        assert query.select[3].alias == "test2"
        assert cast(ast.Field, query.select[3].expr).chain == ["test2"]

        assert isinstance(query.select[4], ast.Call)
        assert query.select[4].name == "argMin"
        assert query.select[4].args == [ast.Field(chain=["test3"]), ast.Field(chain=["timestamp"])]
        assert isinstance(query.select[5], ast.Alias)
        assert query.select[5].alias == "test4"
        assert isinstance(query.select[5].expr, ast.Call)
        assert query.select[5].expr.name == "argMin"
        assert query.select[5].expr.args == [ast.Field(chain=["test4"]), ast.Field(chain=["timestamp"])]

    def test_extend_select(self):
        query = ast.SelectQuery(select=[])
        date_from, date_to = parse_expr("1 = 1"), parse_expr("2 = 2")
        builder = FirstTimeForUserEventsQueryAlternator(query, date_from, date_to)

        builder.extend_select(
            [
                ast.Field(chain=["test"]),
                ast.Alias(alias="test2", expr=ast.Field(chain=["test2"])),
            ]
        )
        builder.extend_select(
            [
                ast.Field(chain=["test3"]),
                ast.Alias(alias="test4", expr=ast.Field(chain=["test4"])),
            ],
            aggregate=True,
        )
        builder.build()

        assert len(query.select) == 6

        assert cast(ast.Field, query.select[2]).chain == ["test"]
        assert isinstance(query.select[3], ast.Alias)
        assert query.select[3].alias == "test2"
        assert cast(ast.Field, query.select[3].expr).chain == ["test2"]

        assert isinstance(query.select[4], ast.Call)
        assert query.select[4].name == "argMin"
        assert query.select[4].args == [ast.Field(chain=["test3"]), ast.Field(chain=["timestamp"])]
        assert isinstance(query.select[5], ast.Alias)
        assert query.select[5].alias == "test4"
        assert isinstance(query.select[5].expr, ast.Call)
        assert query.select[5].expr.name == "argMin"
        assert query.select[5].expr.args == [ast.Field(chain=["test4"]), ast.Field(chain=["timestamp"])]
