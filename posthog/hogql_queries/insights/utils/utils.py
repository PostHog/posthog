from copy import deepcopy
from typing import Optional

from posthog.schema import ActionsNode, BaseMathType, DataWarehouseNode, EventsNode, IntervalType, TrendsQuery

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import compare_interval_length
from posthog.models.team.team import Team, WeekStartDay
from posthog.queries.util import get_trunc_func_ch


def get_start_of_interval_hogql(interval: str, *, team: Team, source: Optional[ast.Expr] = None) -> ast.Expr:
    trunc_func = get_trunc_func_ch(interval)
    trunc_func_args: list[ast.Expr] = [source] if source else [ast.Field(chain=["timestamp"])]
    if trunc_func == "toStartOfWeek":
        trunc_func_args.append(ast.Constant(value=int((WeekStartDay(team.week_start_day or 0)).clickhouse_mode)))
    return ast.Call(name=trunc_func, args=trunc_func_args)


def get_start_of_interval_hogql_str(interval: str, *, team: Team, source: str) -> str:
    trunc_func = get_trunc_func_ch(interval)
    return f"{trunc_func}({source}{f', {int((WeekStartDay(team.week_start_day or 0)).clickhouse_mode)}' if trunc_func == 'toStartOfWeek' else ''})"


def series_should_be_set_to_dau(interval: IntervalType, series: EventsNode | ActionsNode | DataWarehouseNode):
    return (
        series.math == BaseMathType.WEEKLY_ACTIVE and compare_interval_length(interval, ">=", IntervalType.WEEK)
    ) or (series.math == BaseMathType.MONTHLY_ACTIVE and compare_interval_length(interval, ">=", IntervalType.MONTH))


def convert_active_user_math_based_on_interval(query: TrendsQuery) -> TrendsQuery:
    """
    Convert WAU to DAU for week or longer intervals
    Convert MAU to DAU for month or longer intervals

    Works for both TrendsQuery and StickinessQuery

    Args:
        query: Either a TrendsQuery or StickinessQuery instance

    Returns:
        The same type of query that was passed in, with appropriate math conversions
    """
    modified_query = deepcopy(query)

    interval = modified_query.interval or IntervalType.DAY

    for series in modified_query.series:
        # Convert WAU to DAU for week or longer intervals
        # Convert MAU to DAU for month or longer intervals
        if series_should_be_set_to_dau(interval, series):
            series.math = BaseMathType.DAU

    return modified_query
