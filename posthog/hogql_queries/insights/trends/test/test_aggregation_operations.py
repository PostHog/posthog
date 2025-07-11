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
    DataWarehouseNode,
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
        [PropertyMathType.P75, "$browser"],
        [PropertyMathType.P90, "$browser"],
        [PropertyMathType.P95, "$browser"],
        [PropertyMathType.P99, "$browser"],
        [CountPerActorMathType.AVG_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MIN_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MAX_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.MEDIAN_COUNT_PER_ACTOR, None],
        [CountPerActorMathType.P75_COUNT_PER_ACTOR, None],
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
        [PropertyMathType.P75, False],
        [PropertyMathType.P90, False],
        [PropertyMathType.P95, False],
        [PropertyMathType.P99, False],
        [CountPerActorMathType.AVG_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MIN_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MAX_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.MEDIAN_COUNT_PER_ACTOR, True],
        [CountPerActorMathType.P75_COUNT_PER_ACTOR, True],
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


@pytest.mark.django_db
def test_math_multiplier_with_sum():
    team = Team()
    series = EventsNode(event="$pageview", math=PropertyMathType.SUM, math_property="$cost", math_multiplier=0.001)
    query_date_range = QueryDateRange(date_range=None, interval=None, now=datetime.now(), team=team)

    agg_ops = AggregationOperations(team, series, ChartDisplayType.ACTIONS_LINE_GRAPH, query_date_range, False)
    result = agg_ops.select_aggregation()

    assert isinstance(result, ast.Call)
    assert result.name == "ifNull"
    assert len(result.args) == 2

    sum_call = result.args[0]
    assert isinstance(sum_call, ast.Call)
    assert sum_call.name == "sum"
    assert len(sum_call.args) == 1

    mult_call = sum_call.args[0]
    assert isinstance(mult_call, ast.Call)
    assert mult_call.name == "toFloat"
    assert len(mult_call.args) == 1

    actual_mult = mult_call.args[0]
    assert isinstance(actual_mult, ast.ArithmeticOperation)
    assert actual_mult.op == ast.ArithmeticOperationOp.Mult

    field_arg = actual_mult.left
    multiplier_arg = actual_mult.right
    assert isinstance(field_arg, ast.Field)
    assert field_arg.chain == ["properties", "$cost"]
    assert isinstance(multiplier_arg, ast.Constant)
    assert multiplier_arg.value == 0.001


@pytest.mark.django_db
def test_math_multiplier_with_datawarehouse_node():
    team = Team()
    series = DataWarehouseNode(
        id="test_table",
        name="test_table",
        table_name="test_table",
        timestamp_field="timestamp",
        distinct_id_field="distinct_id",
        id_field="id",
        math=PropertyMathType.SUM,
        math_property="cost_micros",
        math_multiplier=1 / 1000000,
        math_property_revenue_currency={"static": "USD"},
    )
    query_date_range = QueryDateRange(date_range=None, interval=None, now=datetime.now(), team=team)

    agg_ops = AggregationOperations(team, series, ChartDisplayType.ACTIONS_LINE_GRAPH, query_date_range, False)
    result = agg_ops.select_aggregation()

    assert isinstance(result, ast.Call)
    assert result.name == "sum"
    assert len(result.args) == 1

    convert_call = result.args[0]
    assert isinstance(convert_call, ast.Call)
    assert convert_call.name == "convertCurrency"
    assert len(convert_call.args) == 4

    mult_expr = convert_call.args[2]
    assert isinstance(mult_expr, ast.ArithmeticOperation)
    assert mult_expr.op == ast.ArithmeticOperationOp.Mult

    field_arg = mult_expr.left
    multiplier_arg = mult_expr.right
    assert isinstance(field_arg, ast.Field)
    assert field_arg.chain == ["cost_micros"]
    assert isinstance(multiplier_arg, ast.Constant)
    assert multiplier_arg.value == 1 / 1000000
