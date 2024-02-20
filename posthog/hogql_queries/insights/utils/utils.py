from typing import List, Optional
from posthog.hogql import ast
from posthog.models.team.team import Team, WeekStartDay
from posthog.queries.util import get_trunc_func_ch


def get_start_of_interval_hogql(interval: str, *, team: Team, source: Optional[ast.Expr] = None) -> ast.Expr:
    trunc_func = get_trunc_func_ch(interval)
    trunc_func_args: List[ast.Expr] = [source] if source else [ast.Field(chain=["timestamp"])]
    if trunc_func == "toStartOfWeek":
        trunc_func_args.append(ast.Constant(value=int((WeekStartDay(team.week_start_day or 0)).clickhouse_mode)))
    return ast.Call(name=trunc_func, args=trunc_func_args)
