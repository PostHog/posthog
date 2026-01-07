from typing import cast

from posthog.schema import HogQLQueryModifiers, InCohortVia

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import InternalHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team, set_default_in_cohort_via
from posthog.hogql.printer.base import _Printer
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.in_cohort import resolve_in_cohorts, resolve_in_cohorts_conjoined
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.transforms.projection_pushdown import pushdown_projections
from posthog.hogql.transforms.property_types import PropertySwapper, build_property_swapper
from posthog.hogql.visitor import clone_expr

from posthog.models.team import Team


def to_printed_hogql(query: ast.Expr, team: Team, modifiers: HogQLQueryModifiers | None = None) -> str:
    """Prints the HogQL query without mutating the node"""
    return prepare_and_print_ast(
        clone_expr(query),
        dialect="hogql",
        context=HogQLContext(
            team_id=team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(team, modifiers),
        ),
        pretty=True,
    )[0]


def prepare_and_print_ast(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> tuple[str, _T_AST | None]:
    prepared_ast = prepare_ast_for_printing(node=node, context=context, dialect=dialect, stack=stack, settings=settings)
    if prepared_ast is None:
        return "", None
    return (
        print_prepared_ast(
            node=prepared_ast,
            context=context,
            dialect=dialect,
            stack=stack,
            settings=settings,
            pretty=pretty,
        ),
        prepared_ast,
    )


def prepare_ast_for_printing(
    node: _T_AST,  # node is mutated
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
) -> _T_AST | None:
    if context.database is None:
        with context.timings.measure("create_hogql_database"):  # Legacy name to keep backwards compatibility
            # Passing both `team_id` and `team` because `team` is not always available in the context
            context.database = Database.create_for(
                context.team_id,
                modifiers=context.modifiers,
                team=context.team,
                timings=context.timings,
            )

    context.modifiers = set_default_in_cohort_via(context.modifiers)

    if context.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED:
        with context.timings.measure("resolve_in_cohorts_conjoined"):
            resolve_in_cohorts_conjoined(node, dialect, context, stack)

    with context.timings.measure("resolve_types"):
        node = resolve_types(
            node,
            context,
            dialect=dialect,
            scopes=[node.type for node in stack if node.type is not None] if stack else None,
        )

    if context.modifiers.optimizeProjections:
        with context.timings.measure("projection_pushdown"):
            node = pushdown_projections(node, context)

    if dialect == "postgres":
        with context.timings.measure("resolve_lazy_tables"):
            resolve_lazy_tables(node, dialect, stack, context)

    if dialect == "clickhouse":
        with context.timings.measure("resolve_property_types"):
            build_property_swapper(node, context)
            if context.property_swapper is None:
                return None

            # It would be nice to be able to run property swapping after we resolve lazy tables, so that logic added onto the lazy tables
            # could pass through the swapper. However, in the PropertySwapper, the group_properties and the S3 Table join
            # rely on the existence of lazy tables in the AST. They must be run before we resolve lazy tables. Because groups are
            # not currently used in any sort of where clause optimization (WhereClauseExtractor or PersonsTable), this is okay.
            # We also have to call the group property swapper manually in `lazy_tables.py` after we do a join
            node = PropertySwapper(
                timezone=context.property_swapper.timezone,
                group_properties=context.property_swapper.group_properties,
                event_properties={},
                person_properties={},
                context=context,
                setTimeZones=False,
            ).visit(node)

        with context.timings.measure("resolve_lazy_tables"):
            resolve_lazy_tables(node, dialect, stack, context)

        with context.timings.measure("swap_properties"):
            node = PropertySwapper(
                timezone=context.property_swapper.timezone,
                group_properties={},
                person_properties=context.property_swapper.person_properties,
                event_properties=context.property_swapper.event_properties,
                context=context,
                setTimeZones=context.modifiers.convertToProjectTimezone is not False,
            ).visit(node)

        # We support global query settings, and local subquery settings.
        # If the global query is a select query with settings, merge the two.
        if isinstance(node, ast.SelectQuery) and node.settings is not None and settings is not None:
            for key, value in node.settings.model_dump().items():
                if value is not None:
                    settings.__setattr__(key, value)
            node.settings = None

    if context.modifiers.inCohortVia == InCohortVia.LEFTJOIN:
        with context.timings.measure("resolve_in_cohorts"):
            resolve_in_cohorts(node, dialect, stack, context)

    # We add a team_id guard right before printing. It's not a separate step here.
    return node


def print_prepared_ast(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> str:
    with context.timings.measure("printer"):
        printer_class: type[_Printer]

        match dialect:
            case "clickhouse":
                printer_class = ClickHousePrinter
            case "postgres":
                printer_class = PostgresPrinter
            case "hogql":
                printer_class = _Printer
            case _:
                raise InternalHogQLError(f"Invalid SQL dialect: {dialect}")

        return printer_class(
            context=context,
            dialect=dialect,
            stack=cast(list[ast.AST], stack or []),
            settings=settings,
            pretty=pretty,
        ).visit(node)
