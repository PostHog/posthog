from datetime import datetime
from typing import Literal, Union, cast

import pytest
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
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
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.append_select(ast.Field(chain=["test"]))
        query_modifier.build()

        assert len(query.select) == 2
        assert cast(ast.Field, query.select[1]).chain == ["test"]

    def test_group_no_pre_existing(self):
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert len(query.group_by) == 1
        assert cast(ast.Field, query.group_by[0]).chain == ["event"]

    def test_group_with_pre_existing(self):
        query = parse_select("SELECT event from events GROUP BY uuid")

        query_modifier = QueryAlternator(query)
        query_modifier.append_group_by(ast.Field(chain=["event"]))
        query_modifier.build()

        assert len(query.group_by) == 2
        assert cast(ast.Field, query.group_by[0]).chain == ["uuid"]
        assert cast(ast.Field, query.group_by[1]).chain == ["event"]

    def test_replace_select_from(self):
        query = parse_select("SELECT event from events")

        query_modifier = QueryAlternator(query)
        query_modifier.replace_select_from(ast.JoinExpr(table=ast.Field(chain=["groups"])))
        query_modifier.build()

        assert query.select_from.table.chain == ["groups"]


@pytest.mark.parametrize(
    "math,math_property",
    [
        [BaseMathType.TOTAL, None],
        [BaseMathType.DAU, None],
        [BaseMathType.WEEKLY_ACTIVE, None],
        [BaseMathType.MONTHLY_ACTIVE, None],
        [BaseMathType.UNIQUE_SESSION, None],
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
