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
        [BaseMathType.total, None],
        [BaseMathType.dau, None],
        [BaseMathType.weekly_active, None],
        [BaseMathType.monthly_active, None],
        [BaseMathType.unique_session, None],
        [PropertyMathType.avg, "$browser"],
        [PropertyMathType.sum, "$browser"],
        [PropertyMathType.min, "$browser"],
        [PropertyMathType.max, "$browser"],
        [PropertyMathType.median, "$browser"],
        [PropertyMathType.p90, "$browser"],
        [PropertyMathType.p95, "$browser"],
        [PropertyMathType.p99, "$browser"],
        [CountPerActorMathType.avg_count_per_actor, None],
        [CountPerActorMathType.min_count_per_actor, None],
        [CountPerActorMathType.max_count_per_actor, None],
        [CountPerActorMathType.median_count_per_actor, None],
        [CountPerActorMathType.p90_count_per_actor, None],
        [CountPerActorMathType.p95_count_per_actor, None],
        [CountPerActorMathType.p99_count_per_actor, None],
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

    agg_ops = AggregationOperations(team, series, query_date_range, False)
    res = agg_ops.select_aggregation()
    assert isinstance(res, ast.Expr)


@pytest.mark.parametrize(
    "math,result",
    [
        [BaseMathType.total, False],
        [BaseMathType.dau, False],
        [BaseMathType.weekly_active, True],
        [BaseMathType.monthly_active, True],
        [BaseMathType.unique_session, False],
        [PropertyMathType.avg, False],
        [PropertyMathType.sum, False],
        [PropertyMathType.min, False],
        [PropertyMathType.max, False],
        [PropertyMathType.median, False],
        [PropertyMathType.p90, False],
        [PropertyMathType.p95, False],
        [PropertyMathType.p99, False],
        [CountPerActorMathType.avg_count_per_actor, True],
        [CountPerActorMathType.min_count_per_actor, True],
        [CountPerActorMathType.max_count_per_actor, True],
        [CountPerActorMathType.median_count_per_actor, True],
        [CountPerActorMathType.p90_count_per_actor, True],
        [CountPerActorMathType.p95_count_per_actor, True],
        [CountPerActorMathType.p99_count_per_actor, True],
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

    agg_ops = AggregationOperations(team, series, query_date_range, False)
    res = agg_ops.requires_query_orchestration()
    assert res == result
