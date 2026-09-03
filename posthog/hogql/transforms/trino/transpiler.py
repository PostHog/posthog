from __future__ import annotations

from typing import Any

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.trino_locator import TrinoTableLocator
from posthog.hogql.printer.trino import TrinoPrinter
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.transforms.trino.normalize import normalize_trino_ast
from posthog.hogql.transforms.trino.validate import validate_trino_ready_ast
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen
from posthog.schema_enums import PersonsOnEventsMode
from posthog.week_start_day import WeekStartDay


@frozen
class TrinoTranspilerInput:
    node: ast.AST
    values: tuple[tuple[str, Any], ...]
    table_locators: tuple[tuple[str, TrinoTableLocator], ...]
    persons_on_events_mode: PersonsOnEventsMode | None
    convert_to_project_timezone: bool | None
    limit_top_select: bool
    limit_context: LimitContext | None
    timezone: str
    week_start_day: WeekStartDay
    within_non_hogql_query: bool = False
    stack: tuple[ast.SelectQuery, ...] = ()
    settings: HogQLGlobalSettings | None = None
    pretty: bool = False


@frozen
class TrinoTranspilerResult:
    sql: str
    values: dict[str, Any]
    prepared_node: ast.AST
    node: ast.AST


def transpile_prepared_hogql_to_trino(transpiler_input: TrinoTranspilerInput) -> TrinoTranspilerResult:
    context = HogQLContext(
        database=None,
        team_id=None,
        team=None,
        user=None,
        enable_select_queries=True,
        limit_top_select=transpiler_input.limit_top_select,
        limit_context=transpiler_input.limit_context,
        within_non_hogql_query=transpiler_input.within_non_hogql_query,
        modifiers=HogQLQueryModifiers(
            personsOnEventsMode=transpiler_input.persons_on_events_mode,
            convertToProjectTimezone=transpiler_input.convert_to_project_timezone,
        ),
        restricted_properties=set(),
        trino_table_locators=dict(transpiler_input.table_locators),
        values=dict(transpiler_input.values),
        timezone=transpiler_input.timezone,
        week_start_day=transpiler_input.week_start_day,
    )
    node = normalize_trino_ast(clone_expr(transpiler_input.node), context)
    node = lower_property_access(node, context)
    validate_trino_ready_ast(node, context)
    prepared_node = clone_expr(node)
    sql = TrinoPrinter(
        context=context,
        stack=list(transpiler_input.stack),
        settings=transpiler_input.settings,
        pretty=transpiler_input.pretty,
    ).visit(node)
    return TrinoTranspilerResult(sql=sql, values=dict(context.values), prepared_node=prepared_node, node=node)
