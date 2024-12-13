from datetime import datetime
from typing import Literal, Union

import pytest

from posthog.hogql import ast
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
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
