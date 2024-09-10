from typing import Optional
from posthog.hogql import ast
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
