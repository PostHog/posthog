from collections.abc import Callable
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

import posthoganalytics
from pydantic import BaseModel

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    DateRange,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

    from posthog.models import Team

INSIGHT_TABLE_FUNCTIONS_FLAG = "hogql-insight-table-functions"

_INTERVAL_FUNCTION_UNITS: dict[str, FunnelConversionWindowTimeUnit] = {
    "toIntervalSecond": FunnelConversionWindowTimeUnit.SECOND,
    "toIntervalMinute": FunnelConversionWindowTimeUnit.MINUTE,
    "toIntervalHour": FunnelConversionWindowTimeUnit.HOUR,
    "toIntervalDay": FunnelConversionWindowTimeUnit.DAY,
    "toIntervalWeek": FunnelConversionWindowTimeUnit.WEEK,
    "toIntervalMonth": FunnelConversionWindowTimeUnit.MONTH,
}


@runtime_checkable
class SupportsTableFunctionQuery(Protocol):
    def to_table_function_query(self) -> ast.SelectQuery: ...


class TableFunctionArguments:
    def __init__(self, function_name: str, args: dict[str, ast.Expr]) -> None:
        self.function_name = function_name
        self._args = args

    def _error(self, name: str, expected: str) -> QueryError:
        return QueryError(f"{self.function_name}(): argument '{name}' must be {expected}")

    def string(self, name: str) -> Optional[str]:
        value = self._args.get(name)
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            return None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        raise self._error(name, "a string")

    def string_list(self, name: str) -> Optional[list[str]]:
        value = self._args.get(name)
        if value is None:
            return None
        if isinstance(value, ast.Array) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.exprs
        ):
            return [item.value for item in value.exprs if isinstance(item, ast.Constant)]
        raise self._error(name, "an array of strings, like ['$pageview', 'signed_up']")

    def interval(self, name: str) -> Optional[tuple[int, FunnelConversionWindowTimeUnit]]:
        value = self._args.get(name)
        if value is None:
            return None
        # The parser turns `interval 7 day` into toIntervalDay(7).
        if (
            isinstance(value, ast.Call)
            and value.name in _INTERVAL_FUNCTION_UNITS
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
            and isinstance(value.args[0].value, int)
            and not isinstance(value.args[0].value, bool)
            and value.args[0].value > 0
        ):
            return value.args[0].value, _INTERVAL_FUNCTION_UNITS[value.name]
        raise self._error(name, "a positive interval, like interval 14 day")


@frozen
class InsightTableFunction:
    name: str
    parameters: frozenset[str]
    required: frozenset[str]
    build_query: Callable[[TableFunctionArguments], BaseModel]


def _build_funnels_query(args: TableFunctionArguments) -> FunnelsQuery:
    steps = args.string_list("steps") or []
    if len(steps) < 2:
        raise QueryError("funnel(): argument 'steps' needs at least 2 events")

    order = args.string("order") or StepOrderValue.ORDERED.value
    if order not in {member.value for member in StepOrderValue}:
        raise QueryError("funnel(): argument 'order' must be 'ordered', 'strict' or 'unordered'")

    funnels_filter = FunnelsFilter(funnelOrderType=StepOrderValue(order), funnelVizType=FunnelVizType.STEPS)
    window = args.interval("window")
    if window is not None:
        funnels_filter.funnelWindowInterval, funnels_filter.funnelWindowIntervalUnit = window

    breakdown = args.string("breakdown")
    date_from = args.string("date_from")
    date_to = args.string("date_to")

    return FunnelsQuery(
        series=[EventsNode(event=step, name=step) for step in steps],
        dateRange=DateRange(date_from=date_from, date_to=date_to) if date_from or date_to else None,
        funnelsFilter=funnels_filter,
        breakdownFilter=(
            BreakdownFilter(breakdown=breakdown, breakdown_type=BreakdownType.EVENT) if breakdown else None
        ),
    )


INSIGHT_TABLE_FUNCTIONS: dict[str, InsightTableFunction] = {
    "funnel": InsightTableFunction(
        name="funnel",
        parameters=frozenset({"steps", "date_from", "date_to", "window", "order", "breakdown"}),
        required=frozenset({"steps"}),
        build_query=_build_funnels_query,
    ),
}


def _is_enabled(team: "Team") -> bool:
    # Fails closed: this runs on the query compile path, so an inconclusive local evaluation must
    # mean "off" rather than an HTTP call, and a flag-service error must not open the gate.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                INSIGHT_TABLE_FUNCTIONS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def get_insight_table_function(node: ast.JoinExpr) -> Optional[InsightTableFunction]:
    if node.table_args is None or not isinstance(node.table, ast.Field) or len(node.table.chain) != 1:
        return None
    return INSIGHT_TABLE_FUNCTIONS.get(str(node.table.chain[0]).lower())


def expand_insight_table_function(
    function: InsightTableFunction, table_args: list[ast.Expr], context: "HogQLContext"
) -> ast.SelectQuery:
    # Deferred: models and the query runner registry, which imports every product's runners,
    # must stay off the import path of the resolver.
    from posthog.hogql_queries.query_runner import get_query_runner  # noqa: PLC0415
    from posthog.models import Team  # noqa: PLC0415

    if context.team is not None:
        team = context.team
    elif context.team_id is not None:
        team = Team.objects.get(pk=context.team_id)
    else:
        raise QueryError(f"{function.name}() needs a project")

    if not _is_enabled(team):
        raise QueryError(f"Unknown table function {function.name}()")

    args: dict[str, ast.Expr] = {}
    for arg in table_args:
        if not isinstance(arg, ast.NamedArgument):
            raise QueryError(f"{function.name}() only takes named arguments, like steps := ['$pageview', 'signed_up']")
        if arg.name not in function.parameters:
            allowed = ", ".join(sorted(function.parameters))
            raise QueryError(f"{function.name}() has no argument '{arg.name}'. Arguments: {allowed}")
        if arg.name in args:
            raise QueryError(f"{function.name}(): argument '{arg.name}' is set twice")
        args[arg.name] = arg.value

    missing = sorted(function.required - args.keys())
    if missing:
        raise QueryError(f"{function.name}() is missing required argument '{missing[0]}'")

    query_node = function.build_query(TableFunctionArguments(function.name, args))
    runner = get_query_runner(query_node, team)
    if not isinstance(runner, SupportsTableFunctionQuery):
        raise QueryError(f"{function.name}() is not available")
    return runner.to_table_function_query()
