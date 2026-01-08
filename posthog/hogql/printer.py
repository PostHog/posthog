import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from difflib import get_close_matches
from typing import Literal, Optional, Union, cast
from uuid import UUID

from django.conf import settings as django_settings

from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    MaterializationMode,
    MaterializedColumnsOptimizationMode,
    PersonsOnEventsMode,
    PropertyGroupsMode,
)

from posthog.hogql import ast
from posthog.hogql.ast import Constant, StringType
from posthog.hogql.base import _T_AST, AST
from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings, LimitContext, get_max_limit_for_context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    DatabaseField,
    FunctionCallTable,
    SavedQuery,
    Table,
)
from posthog.hogql.database.s3_table import DataWarehouseTable, S3Table
from posthog.hogql.errors import ImpossibleASTError, InternalHogQLError, QueryError, ResolutionError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
    escape_postgres_identifier,
    safe_identifier,
)
from posthog.hogql.functions import (
    ADD_OR_NULL_DATETIME_FUNCTIONS,
    FIRST_ARG_DATETIME_FUNCTIONS,
    find_hogql_aggregation,
    find_hogql_function,
    find_hogql_posthog_function,
)
from posthog.hogql.functions.core import validate_function_args
from posthog.hogql.functions.embed_text import resolve_embed_text
from posthog.hogql.functions.mapping import (
    ALL_EXPOSED_FUNCTION_NAMES,
    HOGQL_COMPARISON_MAPPING,
    is_allowed_parametric_function,
)
from posthog.hogql.modifiers import create_default_modifiers_for_team, set_default_in_cohort_via
from posthog.hogql.resolver import resolve_types
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.transforms.in_cohort import resolve_in_cohorts, resolve_in_cohorts_conjoined
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.transforms.projection_pushdown import pushdown_projections
from posthog.hogql.transforms.property_types import PropertySwapper, build_property_swapper
from posthog.hogql.visitor import Visitor, clone_expr

from posthog.clickhouse.materialized_columns import (
    MaterializedColumn,
    TablesWithMaterializedColumns,
    get_materialized_column_for_property,
)
from posthog.clickhouse.property_groups import property_groups
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DICTIONARY_NAME
from posthog.models.property import PropertyName, TableColumn
from posthog.models.surveys.util import (
    filter_survey_sent_events_by_unique_submission,
    get_survey_response_clickhouse_query,
)
from posthog.models.team import Team
from posthog.models.team.team import WeekStartDay
from posthog.models.utils import UUIDT


def get_channel_definition_dict():
    """Get the channel definition dictionary name with the correct database.
    Evaluated at call time to work with test databases in Python 3.12."""
    return f"{django_settings.CLICKHOUSE_DATABASE}.channel_definition_dict"


def team_id_guard_for_table(table_type: Union[ast.TableType, ast.TableAliasType], context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.team_id:
        raise InternalHogQLError("context.team_id not found")

    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["team_id"], type=ast.FieldType(name="team_id", table_type=table_type)),
        right=ast.Constant(value=context.team_id),
        type=ast.BooleanType(),
    )


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
) -> tuple[str, Optional[_T_AST]]:
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
        node = resolve_types(node, context, dialect=dialect, scopes=[node.type for node in stack] if stack else None)

    if context.modifiers.optimizeProjections:
        with context.timings.measure("projection_pushdown"):
            node = pushdown_projections(node, context)

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
            stack=stack or [],
            settings=settings,
            pretty=pretty,
        ).visit(node)


@dataclass
class JoinExprResponse:
    printed_sql: str
    where: ast.Expr | None = None


@dataclass
class PrintableMaterializedColumn:
    table: str | None
    column: str
    is_nullable: bool

    def __str__(self) -> str:
        if self.table is None:
            # XXX: For legacy person properties handling (see comment at instantiation site.)
            return self.column
        else:
            return f"{self.table}.{self.column}"


@dataclass
class PrintableMaterializedPropertyGroupItem:
    table: str
    column: str
    property_name: str

    def __str__(self) -> str:
        # If the key we're looking for doesn't exist in the map for this property group, an empty string (the default
        # value for the `String` type) is returned. Since that is a valid property value, we need to check it here.
        return f"{self.has_expr} ? {self.value_expr} : null"

    @property
    def __qualified_column(self) -> str:
        return f"{self.table}.{self.column}"

    @property
    def has_expr(self) -> str:
        return f"has({self.__qualified_column}, {self.property_name})"

    @property
    def value_expr(self) -> str:
        return f"{self.__qualified_column}[{self.property_name}]"


def resolve_field_type(expr: ast.Expr) -> ast.Type | None:
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    return expr_type


class _Printer(Visitor[str]):
    # NOTE: Call "print_ast()", not this class directly.

    def __init__(
        self,
        context: HogQLContext,
        dialect: HogQLDialect,
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        self.context = context
        self.dialect = dialect
        self.stack: list[AST] = stack or []  # Keep track of all traversed nodes.
        self.settings = settings
        self.pretty = pretty
        self._indent = -1
        self.tab_size = 4

    def indent(self, extra: int = 0):
        return " " * self.tab_size * (self._indent + extra)

    def visit(self, node: AST | None):
        if node is None:
            return ""
        self.stack.append(node)
        self._indent += 1
        response = super().visit(node)
        self._indent -= 1
        self.stack.pop()

        return response

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        self._indent -= 1
        ret = self.visit(node.initial_select_query)
        if self.pretty:
            ret = ret.strip()
        for expr in node.subsequent_select_queries:
            query = self.visit(expr.select_query)
            if self.pretty:
                query = query.strip()
            if expr.set_operator is not None:
                if self.pretty:
                    ret += f"\n{self.indent(1)}{expr.set_operator}\n{self.indent(1)}"
                else:
                    ret += f" {expr.set_operator} "
            ret += query
        self._indent += 1
        if len(self.stack) > 1:
            return f"({ret.strip()})"
        return ret

    def visit_select_query(self, node: ast.SelectQuery):
        # if we are the first parsed node in the tree, or a child of a SelectSetQuery, mark us as a top level query
        part_of_select_union = len(self.stack) >= 2 and isinstance(self.stack[-2], ast.SelectSetQuery)
        is_top_level_query = len(self.stack) <= 1 or (len(self.stack) == 2 and part_of_select_union)
        is_last_query_in_union = (
            part_of_select_union
            and isinstance(self.stack[0], ast.SelectSetQuery)
            and len(self.stack[0].subsequent_select_queries) > 0
            and self.stack[0].subsequent_select_queries[-1].select_query is node
        )

        # We will add extra clauses onto this from the joined tables
        where = node.where

        joined_tables = []
        next_join = node.select_from
        while isinstance(next_join, ast.JoinExpr):
            if next_join.type is None:
                if self.dialect == "clickhouse":
                    raise InternalHogQLError(
                        "Printing queries with a FROM clause is not permitted before type resolution"
                    )

            visited_join = self.visit_join_expr(next_join)
            joined_tables.append(visited_join.printed_sql)

            # This is an expression we must add to the SELECT's WHERE clause to limit results, like the team ID guard.
            extra_where = visited_join.where
            if extra_where is None:
                pass
            elif isinstance(extra_where, ast.Expr):
                if where is None:
                    where = extra_where
                elif isinstance(where, ast.And):
                    where = ast.And(exprs=[extra_where, *where.exprs])
                else:
                    where = ast.And(exprs=[extra_where, where])
            else:
                raise ImpossibleASTError(
                    f"Invalid where of type {type(extra_where).__name__} returned by join_expr", node=visited_join.where
                )

            next_join = next_join.next_join

        if node.select:
            if self.dialect == "clickhouse":
                # Gather all visible aliases, and/or the last hidden alias for each unique alias name.
                found_aliases = {}
                for alias in reversed(node.select):
                    if isinstance(alias, ast.Alias):
                        if not found_aliases.get(alias.alias, None) or not alias.hidden:
                            found_aliases[alias.alias] = alias

                columns = []
                for column in node.select:
                    if isinstance(column, ast.Alias):
                        # It's either a visible alias, or the last hidden alias with this name.
                        if found_aliases.get(column.alias) == column:
                            if column.hidden:
                                # Make the hidden alias visible
                                column = cast(ast.Alias, clone_expr(column))
                                column.hidden = False
                            else:
                                # Always print visible aliases.
                                pass
                        else:
                            # Non-unique hidden alias. Skip.
                            column = column.expr
                    elif isinstance(column, ast.Call):
                        column_alias = safe_identifier(print_prepared_ast(column, self.context, dialect="hogql"))
                        column = ast.Alias(alias=column_alias, expr=column)
                    columns.append(self.visit(column))
            else:
                columns = [self.visit(column) for column in node.select]
        else:
            columns = ["1"]
        window = (
            ", ".join(
                [f"{self._print_identifier(name)} AS ({self.visit(expr)})" for name, expr in node.window_exprs.items()]
            )
            if node.window_exprs
            else None
        )
        prewhere = self.visit(node.prewhere) if node.prewhere else None
        where = self.visit(where) if where else None
        group_by = [self.visit(column) for column in node.group_by] if node.group_by else None
        having = self.visit(node.having) if node.having else None
        order_by = [self.visit(column) for column in node.order_by] if node.order_by else None

        array_join = ""
        if node.array_join_op is not None:
            if node.array_join_op not in (
                "ARRAY JOIN",
                "LEFT ARRAY JOIN",
                "INNER ARRAY JOIN",
            ):
                raise ImpossibleASTError(f"Invalid ARRAY JOIN operation: {node.array_join_op}")
            array_join = node.array_join_op
            if len(node.array_join_list) == 0:
                raise ImpossibleASTError(f"Invalid ARRAY JOIN without an array")
            array_join += f" {', '.join(self.visit(expr) for expr in node.array_join_list)}"

        space = f"\n{self.indent(1)}" if self.pretty else " "
        comma = f",\n{self.indent(1)}" if self.pretty else ", "

        clauses = [
            f"SELECT{space}{'DISTINCT ' if node.distinct else ''}{comma.join(columns)}",
            f"FROM{space}{space.join(joined_tables)}" if len(joined_tables) > 0 else None,
            array_join if array_join else None,
            f"PREWHERE{space}" + prewhere if prewhere else None,
            f"WHERE{space}" + where if where else None,
            f"GROUP BY{space}{comma.join(group_by)}" if group_by and len(group_by) > 0 else None,
            f"HAVING{space}" + having if having else None,
            f"WINDOW{space}" + window if window else None,
            f"ORDER BY{space}{comma.join(order_by)}" if order_by and len(order_by) > 0 else None,
        ]

        limit = node.limit
        if self.context.limit_top_select and is_top_level_query:
            max_limit = get_max_limit_for_context(self.context.limit_context or LimitContext.QUERY)

            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, max_limit)
                else:
                    limit = ast.Call(
                        name="min2",
                        args=[ast.Constant(value=max_limit), limit],
                    )
            else:
                limit = ast.Constant(value=max_limit)

        if node.limit_by is not None:
            clauses.append(
                f"LIMIT {self.visit(node.limit_by.n)} {f'OFFSET {self.visit(node.limit_by.offset_value)}' if node.limit_by.offset_value else ''} BY {', '.join([self.visit(expr) for expr in node.limit_by.exprs])}"
            )

        if limit is not None:
            clauses.append(f"LIMIT {self.visit(limit)}")
            if node.limit_with_ties:
                clauses.append("WITH TIES")

        if node.offset is not None:
            clauses.append(f"OFFSET {self.visit(node.offset)}")

        if (
            self.context.output_format
            and self.dialect == "clickhouse"
            and is_top_level_query
            and (not part_of_select_union or is_last_query_in_union)
        ):
            clauses.append(f"FORMAT{space}{self.context.output_format}")

        if node.settings is not None and self.dialect == "clickhouse":
            settings = self._print_settings(node.settings)
            if settings is not None:
                clauses.append(settings)

        if self.pretty:
            response = "\n".join([f"{self.indent()}{clause}" for clause in clauses if clause is not None])
        else:
            response = " ".join([clause for clause in clauses if clause is not None])

        # If we are printing a SELECT subquery (not the first AST node we are visiting), wrap it in parentheses.
        if not part_of_select_union and not is_top_level_query:
            if self.pretty:
                response = f"({response.strip()})"
            else:
                response = f"({response})"

        return response

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        # return constraints we must place on the select query
        extra_where: ast.Expr | None = None

        join_strings = []

        if node.join_type is not None:
            join_strings.append(node.join_type)

        if isinstance(node.type, ast.TableAliasType) or isinstance(node.type, ast.TableType):
            table_type = node.type
            while isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type

            if not isinstance(table_type, ast.TableType) and not isinstance(table_type, ast.LazyTableType):
                raise ImpossibleASTError(f"Invalid table type {type(table_type).__name__} in join_expr")

            if self.dialect == "clickhouse":
                # :IMPORTANT: This assures a "team_id" where clause is present on every selected table.
                # Skip warehouse tables and tables with an explicit skip.
                if (
                    not isinstance(table_type.table, DataWarehouseTable)
                    and not isinstance(table_type.table, SavedQuery)
                    and not isinstance(table_type.table, DANGEROUS_NoTeamIdCheckTable)
                ):
                    extra_where = team_id_guard_for_table(node.type, self.context)

                sql = table_type.table.to_printed_clickhouse(self.context)

                # Edge case. If we are joining an s3 table, we must wrap it in a subquery for the join to work
                if isinstance(table_type.table, S3Table) and (
                    node.next_join
                    or node.join_type == "JOIN"
                    or (node.join_type and node.join_type.startswith("GLOBAL "))
                ):
                    sql = f"(SELECT * FROM {sql})"
            elif self.dialect == "hogql":
                sql = table_type.table.to_printed_hogql()
            elif self.dialect == "postgres":
                sql = table_type.table.to_printed_postgres()
            else:
                raise ImpossibleASTError(f"Unsupported dialect {self.dialect}")

            if isinstance(table_type.table, FunctionCallTable) and table_type.table.requires_args:
                if node.table_args is None:
                    raise QueryError(f"Table function '{table_type.table.name}' requires arguments")

                if table_type.table.min_args is not None and (
                    node.table_args is None or len(node.table_args) < table_type.table.min_args
                ):
                    raise QueryError(
                        f"Table function '{table_type.table.name}' requires at least {table_type.table.min_args} argument{'s' if table_type.table.min_args > 1 else ''}"
                    )
                if table_type.table.max_args is not None and (
                    node.table_args is None or len(node.table_args) > table_type.table.max_args
                ):
                    raise QueryError(
                        f"Table function '{table_type.table.name}' requires at most {table_type.table.max_args} argument{'s' if table_type.table.max_args > 1 else ''}"
                    )
                if node.table_args is not None and len(node.table_args) > 0:
                    sql = f"{sql}({', '.join([self.visit(arg) for arg in node.table_args])})"
            elif node.table_args is not None:
                raise QueryError(f"Table '{table_type.table.to_printed_hogql()}' does not accept arguments")

            join_strings.append(sql)

            if isinstance(node.type, ast.TableAliasType) and node.alias is not None and node.alias != sql:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectSetQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectViewType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryAliasType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.LazyTableType):
            if self.dialect == "hogql":
                join_strings.append(self._print_identifier(node.type.table.to_printed_hogql()))
            else:
                raise ImpossibleASTError(f"Unexpected LazyTableType for: {node.type.table.to_printed_hogql()}")

        elif self.dialect == "hogql":
            join_strings.append(self.visit(node.table))
            if node.alias is not None:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")
        else:
            raise QueryError(
                f"Only selecting from a table or a subquery is supported. Unexpected type: {node.type.__class__.__name__}"
            )

        if node.table_final:
            join_strings.append("FINAL")

        if node.sample is not None:
            sample_clause = self.visit_sample_expr(node.sample)
            if sample_clause is not None:
                join_strings.append(sample_clause)

        if node.constraint is not None:
            join_strings.append(f"{node.constraint.constraint_type} {self.visit(node.constraint)}")

        return JoinExprResponse(printed_sql=" ".join(join_strings), where=extra_where)

    def visit_join_constraint(self, node: ast.JoinConstraint):
        return self.visit(node.expr)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        if node.op == ast.ArithmeticOperationOp.Add:
            return f"plus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Sub:
            return f"minus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mult:
            return f"multiply({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Div:
            return f"divide({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mod:
            return f"modulo({self.visit(node.left)}, {self.visit(node.right)})"
        else:
            raise ImpossibleASTError(f"Unknown ArithmeticOperationOp {node.op}")

    def visit_and(self, node: ast.And):
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        return f"and({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_or(self, node: ast.Or):
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        return f"or({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_not(self, node: ast.Not):
        return f"not({self.visit(node.expr)})"

    def visit_tuple_access(self, node: ast.TupleAccess):
        visited_tuple = self.visit(node.tuple)
        visited_index = int(str(node.index))
        symbol = "?." if self.dialect == "hogql" and node.nullish else "."
        if isinstance(node.tuple, ast.Field) or isinstance(node.tuple, ast.Tuple) or isinstance(node.tuple, ast.Call):
            return f"{visited_tuple}{symbol}{visited_index}"
        return f"({visited_tuple}){symbol}{visited_index}"

    def _visit_postgres_tuple(self, node: ast.Tuple) -> str:
        values = [self.visit(expr) for expr in node.exprs]

        if len(values) == 1:
            # Parentheses around a single value are just grouping in Postgres. Use ROW() to construct a 1-column tuple.
            return f"ROW({values[0]})"

        return f"({', '.join(values)})"

    def visit_tuple(self, node: ast.Tuple):
        if self.dialect == "postgres":
            return self._visit_postgres_tuple(node)

        return f"tuple({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_array_access(self, node: ast.ArrayAccess):
        symbol = "?." if self.dialect == "hogql" and node.nullish else ""
        return f"{self.visit(node.array)}{symbol}[{self.visit(node.property)}]"

    def visit_array(self, node: ast.Array):
        return f"[{', '.join([self.visit(expr) for expr in node.exprs])}]"

    def visit_dict(self, node: ast.Dict):
        tuple_function = "ROW" if self.dialect == "postgres" else "tuple"
        str = f"{tuple_function}('__hx_tag', '__hx_obj'"
        for key, value in node.items:
            str += f", {self.visit(key)}, {self.visit(value)}"
        return str + ")"

    def visit_lambda(self, node: ast.Lambda):
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if len(identifiers) == 0:
            raise ValueError("Lambdas require at least one argument")
        elif len(identifiers) == 1:
            return f"{identifiers[0]} -> {self.visit(node.expr)}"
        return f"({', '.join(identifiers)}) -> {self.visit(node.expr)}"

    def visit_order_expr(self, node: ast.OrderExpr):
        return f"{self.visit(node.expr)} {node.order}"

    def __optimize_in_with_string_values(
        self, values: list[ast.Expr], property_source: PrintableMaterializedPropertyGroupItem
    ) -> str | None:
        """
        Optimizes an IN comparison against a list of values for property group bloom filter usage.
        Returns the optimized expression string, or None if optimization is not possible.
        """
        # Bail on the optimisation if any value is not a Constant, is the empty string, is NULL, or is not a string
        for v in values:
            if not isinstance(v, ast.Constant):
                return None
            if v.value == "" or v.value is None or not isinstance(v.value, str):
                return None

        # IN with an empty set of values is always false
        if len(values) == 0:
            return "0"

        # A problem we run into here is that an expression like
        # in(events.properties_group_feature_flags['$feature/onboarding-use-case-selection'], ('control', 'test'))
        # does not hit the bloom filter on the key, so we need to modify the expression so that it does

        # If only one value, switch to equality operator. Expressions like this will hit the bloom filter for both keys and values:
        # events.properties_group_feature_flags['$feature/onboarding-use-case-selection'] = 'control'
        if len(values) == 1:
            return f"equals({property_source.value_expr}, {self.visit(values[0])})"

        # With transform_null_in=1 in SETTINGS (which we have by default), if there are several values, we need to
        # include a check for whether the key exists to hit the keys bloom filter.
        # Unlike the version WITHOUT mapKeys above, the following expression WILL hit the bloom filter:
        # and(has(mapKeys(properties_group_feature_flags), '$feature/onboarding-use-case-selection'),
        #     in(events.properties_group_feature_flags['$feature/onboarding-use-case-selection'], ('control', 'test')))
        # Note that we could add a mapValues to this to use the values bloom filter
        # TODO to profile whether we should add mapValues. Probably no for flags, yes for properties.
        values_tuple = ", ".join(self.visit(v) for v in values)
        return f"and({property_source.has_expr}, in({property_source.value_expr}, tuple({values_tuple})))"

    def _get_optimized_property_group_compare_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns a printed expression corresponding to the provided compare operation, if one of the operands is part of
        a property group value and: the comparison can be rewritten so that it can be eligible for use by one or more
        the property group's bloom filter data skipping indices, or the expression can be optimized to avoid reading the
        property group's map ``values`` subcolumn when doing comparisons to NULL values.
        """
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            # For commutative operations, we can rewrite the expression with parameters in either order without
            # affecting the result.
            # NOTE: For now, this only works with comparisons to constant values directly since we need to know whether
            # or not the non-``PropertyType`` operand is ``NULL`` to be able to rewrite the expression to the correct
            # optimized version. This could be extended to support *any* non-``Nullable`` expression as well, so that
            # expressions which do not reference a field as part of the expression (and therefore can be resolved to a
            # constant value during the initial stages of query execution, e.g. ``lower(concat('X', 'Y'))`` ) can also
            # utilize the index. (The same applies to ``In`` comparisons below, too.)
            property_type: ast.PropertyType | None = None
            constant_expr: ast.Constant | None = None

            # TODO: This doesn't resolve aliases for the constant operand, so this does not comprehensively cover all
            # optimizable expressions, but that case seems uncommon enough to avoid for now.
            if isinstance(node.right, ast.Constant):
                left_type = resolve_field_type(node.left)
                if isinstance(left_type, ast.PropertyType):
                    property_type = left_type
                    constant_expr = node.right
            elif isinstance(node.left, ast.Constant):
                right_type = resolve_field_type(node.right)
                if isinstance(right_type, ast.PropertyType):
                    property_type = right_type
                    constant_expr = node.left

            # TODO: Chained properties could likely be supported here to at least use the keys index.
            if property_type is None or len(property_type.chain) > 1:
                return None
            else:
                assert constant_expr is not None  # appease mypy - if we got this far, we should have a constant

            property_source = self._get_materialized_property_source_for_property_type(property_type)
            if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                return None

            if node.op == ast.CompareOperationOp.Eq:
                if constant_expr.value is None:
                    # "IS NULL" can be interpreted as "does not exist in the map" -- this avoids unnecessarily reading
                    # the ``values`` subcolumn of the map.
                    return f"not({property_source.has_expr})"

                # Equality comparisons to boolean constants can skip NULL checks while maintaining our desired result
                # (i.e. comparisons with NULL evaluate to false) since the value expression will return an empty string
                # if the property doesn't exist in the map.
                if constant_expr.value is True:
                    return f"equals({property_source.value_expr}, 'true')"
                elif constant_expr.value is False:
                    return f"equals({property_source.value_expr}, 'false')"

                if isinstance(constant_expr.type, ast.StringType):
                    printed_expr = f"equals({property_source.value_expr}, {self.visit(constant_expr)})"
                    if constant_expr.value == "":
                        # If we're comparing to an empty string literal, we need to disambiguate this from the default value
                        # for the ``Map(String, String)`` type used for storing property group values by also ensuring that
                        # the property key is present in the map. If this is in a ``WHERE`` clause, this also ensures we can
                        # still use the data skipping index on keys, even though the values index cannot be used.
                        printed_expr = f"and({property_source.has_expr}, {printed_expr})"

                    return printed_expr

            elif node.op == ast.CompareOperationOp.NotEq:
                if constant_expr.value is None:
                    # "IS NOT NULL" can be interpreted as "does exist in the map" -- this avoids unnecessarily reading
                    # the ``values`` subcolumn of the map, and also allows us to use the data skipping index on keys.
                    return property_source.has_expr

        elif node.op in (ast.CompareOperationOp.In):
            # ``IN`` is _not_ commutative, so we only need to check the left side operand (in contrast with above.)
            left_type = resolve_field_type(node.left)
            if not isinstance(left_type, ast.PropertyType):
                return None

            # TODO: Chained properties could likely be supported here to at least use the keys index.
            if left_type is None or len(left_type.chain) > 1:
                return None

            property_source = self._get_materialized_property_source_for_property_type(left_type)
            if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                return None

            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    # we can't optimize here, as the unoptimized version returns true if the key doesn't exist OR the value is null
                    return None
                if node.right.value == "":
                    # If the RHS is the empty string, we need to disambiguate it from the default value for missing keys.
                    return f"and({property_source.has_expr}, equals({property_source.value_expr}, {self.visit(node.right)}))"
                elif isinstance(node.right.type, ast.StringType):
                    return f"equals({property_source.value_expr}, {self.visit(node.right)})"
            elif isinstance(node.right, ast.Tuple) or isinstance(node.right, ast.Array):
                return self.__optimize_in_with_string_values(node.right.exprs, property_source)
            else:
                # TODO: Alias types are not resolved here (similarly to equality operations above) so some expressions
                # are not optimized that possibly could be if we took that additional step to determine whether or not
                # they are references to Constant types.
                return None

        return None  # nothing to optimize

    def _get_optimized_materialized_column_compare_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns an optimized printed expression for comparisons involving individually materialized columns.

        When comparing a materialized column to a non-empty, non-null string constant, we can skip the
        nullIf() wrapping that normally happens. This allows ClickHouse to use skip indexes on the
        materialized column.

        For example, instead of:
            ifNull(equals(nullIf(nullIf(events.`mat_$feature_flag`, ''), 'null'), 'some_value'), 0)
        We can emit:
            equals(events.`mat_$feature_flag`, 'some_value')

        This is safe because we know 'some_value' is neither empty string nor 'null', so the nullIf
        checks are redundant for the comparison result.
        """
        if self.context.modifiers.materializedColumnsOptimizationMode != MaterializedColumnsOptimizationMode.OPTIMIZED:
            return None

        if node.op not in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            return None

        property_type: ast.PropertyType | None = None
        constant_expr: ast.Constant | None = None

        if isinstance(node.right, ast.Constant):
            left_type = resolve_field_type(node.left)
            if isinstance(left_type, ast.PropertyType):
                property_type = left_type
                constant_expr = node.right
        elif isinstance(node.left, ast.Constant):
            right_type = resolve_field_type(node.right)
            if isinstance(right_type, ast.PropertyType):
                property_type = right_type
                constant_expr = node.left

        if property_type is None or constant_expr is None:
            return None

        # Only optimize simple property access (not chained like properties.foo.bar)
        if len(property_type.chain) != 1:
            return None

        # Only optimize for non-empty, non-null string constants
        if not isinstance(constant_expr.value, str):
            return None
        if constant_expr.value == "" or constant_expr.value == "null":
            return None

        # Check if this property uses an individually materialized column (not a property group)
        property_source = self._get_materialized_property_source_for_property_type(property_type)
        if not isinstance(property_source, PrintableMaterializedColumn):
            return None

        # Build the optimized comparison using the raw materialized column
        materialized_column_sql = str(property_source)
        constant_sql = self.visit(constant_expr)

        if node.op == ast.CompareOperationOp.Eq:
            return f"equals({materialized_column_sql}, {constant_sql})"
        else:  # NotEq
            return f"notEquals({materialized_column_sql}, {constant_sql})"

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Eq:
            return f"equals({left}, {right})"
        elif op == ast.CompareOperationOp.NotEq:
            return f"notEquals({left}, {right})"
        elif op == ast.CompareOperationOp.Like:
            return f"like({left}, {right})"
        elif op == ast.CompareOperationOp.NotLike:
            return f"notLike({left}, {right})"
        elif op == ast.CompareOperationOp.ILike:
            return f"ilike({left}, {right})"
        elif op == ast.CompareOperationOp.NotILike:
            return f"notILike({left}, {right})"
        elif op == ast.CompareOperationOp.In:
            return f"in({left}, {right})"
        elif op == ast.CompareOperationOp.NotIn:
            return f"notIn({left}, {right})"
        elif op == ast.CompareOperationOp.GlobalIn:
            return f"globalIn({left}, {right})"
        elif op == ast.CompareOperationOp.GlobalNotIn:
            return f"globalNotIn({left}, {right})"
        elif op == ast.CompareOperationOp.Regex:
            return f"match({left}, {right})"
        elif op == ast.CompareOperationOp.NotRegex:
            return f"not(match({left}, {right}))"
        elif op == ast.CompareOperationOp.IRegex:
            return f"match({left}, concat('(?i)', {right}))"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f"not(match({left}, concat('(?i)', {right})))"
        elif op == ast.CompareOperationOp.Gt:
            return f"greater({left}, {right})"
        elif op == ast.CompareOperationOp.GtEq:
            return f"greaterOrEquals({left}, {right})"
        elif op == ast.CompareOperationOp.Lt:
            return f"less({left}, {right})"
        elif op == ast.CompareOperationOp.LtEq:
            return f"lessOrEquals({left}, {right})"
        # only used for hogql direct printing (no prepare called)
        elif op == ast.CompareOperationOp.InCohort and self.dialect == "hogql":
            return f"{left} IN COHORT {right}"
        # only used for hogql direct printing (no prepare called)
        elif op == ast.CompareOperationOp.NotInCohort and self.dialect == "hogql":
            return f"{left} NOT IN COHORT {right}"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {op.name}")

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)
        right = self.visit(node.right)
        return self._get_compare_op(node.op, left, right)

    def visit_between_expr(self, node: ast.BetweenExpr):
        expr = self.visit(node.expr)
        low = self.visit(node.low)
        high = self.visit(node.high)
        not_kw = " NOT" if node.negated else ""
        op = f"{expr}{not_kw} BETWEEN {low} AND {high}"

        return op

    def visit_constant(self, node: ast.Constant):
        # Inline everything in HogQL
        return self._print_escaped_string(node.value)

    def visit_field(self, node: ast.Field):
        if node.chain == ["*"]:
            return "*"
        # When printing HogQL, we print the properties out as a chain as they are.
        return ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])

    def visit_call(self, node: ast.Call):
        func_meta = (
            find_hogql_aggregation(node.name)
            or find_hogql_function(node.name)
            or find_hogql_posthog_function(node.name)
        )

        # Validate parametric arguments
        if func_meta:
            if func_meta.parametric_first_arg:
                if not node.args:
                    raise QueryError(f"Missing arguments in function '{node.name}'")
                # Check that the first argument is a constant string
                first_arg = node.args[0]
                if not isinstance(first_arg, ast.Constant):
                    raise QueryError(
                        f"Expected constant string as first arg in function '{node.name}', got {first_arg.__class__.__name__}"
                    )
                if not isinstance(first_arg.type, StringType) or not isinstance(first_arg.value, str):
                    raise QueryError(
                        f"Expected constant string as first arg in function '{node.name}', got {first_arg.type.__class__.__name__} '{first_arg.value}'"
                    )
                # Check that the constant string is within our allowed set of functions
                if not is_allowed_parametric_function(first_arg.value):
                    raise QueryError(
                        f"Invalid parametric function in '{node.name}', '{first_arg.value}' is not supported."
                    )

            # Handle format strings in function names before checking function type
            if func_meta.using_placeholder_arguments:
                # Check if using positional arguments (e.g. {0}, {1})
                if func_meta.using_positional_arguments:
                    # For positional arguments, pass the args as a dictionary
                    arg_arr = [self.visit(arg) for arg in node.args]
                    try:
                        return func_meta.clickhouse_name.format(*arg_arr)
                    except (KeyError, IndexError) as e:
                        raise QueryError(f"Invalid argument reference in function '{node.name}': {str(e)}")
                else:
                    # Original sequential placeholder behavior
                    placeholder_count = func_meta.clickhouse_name.count("{}")
                    if len(node.args) != placeholder_count:
                        raise QueryError(
                            f"Function '{node.name}' requires exactly {placeholder_count} argument{'s' if placeholder_count != 1 else ''}"
                        )
                    return func_meta.clickhouse_name.format(*[self.visit(arg) for arg in node.args])

        if node.name in HOGQL_COMPARISON_MAPPING:
            op = HOGQL_COMPARISON_MAPPING[node.name]
            if len(node.args) != 2:
                raise QueryError(f"Comparison '{node.name}' requires exactly two arguments")
            # We do "cleverer" logic with nullable types in visit_compare_operation
            return self.visit_compare_operation(
                ast.CompareOperation(
                    left=node.args[0],
                    right=node.args[1],
                    op=op,
                )
            )
        elif func_meta := find_hogql_aggregation(node.name):
            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
                function_term="aggregation",
            )
            if func_meta.min_params:
                if node.params is None:
                    raise QueryError(f"Aggregation '{node.name}' requires parameters in addition to arguments")
                validate_function_args(
                    node.params,
                    func_meta.min_params,
                    func_meta.max_params,
                    node.name,
                    function_term="aggregation",
                    argument_term="parameter",
                )

            # check that we're not running inside another aggregate
            for stack_node in reversed(self.stack):
                if isinstance(stack_node, ast.SelectQuery):
                    break
                if stack_node != node and isinstance(stack_node, ast.Call) and find_hogql_aggregation(stack_node.name):
                    raise QueryError(
                        f"Aggregation '{node.name}' cannot be nested inside another aggregation '{stack_node.name}'."
                    )

            arg_strings = [self.visit(arg) for arg in node.args]
            params = [self.visit(param) for param in node.params] if node.params is not None else None

            params_part = f"({', '.join(params)})" if params is not None else ""
            args_part = f"({f'DISTINCT ' if node.distinct else ''}{', '.join(arg_strings)})"

            return f"{node.name if self.dialect == 'hogql' else func_meta.clickhouse_name}{params_part}{args_part}"

        elif func_meta := find_hogql_function(node.name):
            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
            )

            if func_meta.min_params:
                if node.params is None:
                    raise QueryError(f"Function '{node.name}' requires parameters in addition to arguments")
                validate_function_args(
                    node.params,
                    func_meta.min_params,
                    func_meta.max_params,
                    node.name,
                    argument_term="parameter",
                )

            if self.dialect == "clickhouse":
                args_count = len(node.args) - func_meta.passthrough_suffix_args_count
                node_args, passthrough_suffix_args = node.args[:args_count], node.args[args_count:]

                if node.name in FIRST_ARG_DATETIME_FUNCTIONS:
                    args: list[str] = []
                    for idx, arg in enumerate(node_args):
                        if idx == 0:
                            if isinstance(arg, ast.Call) and arg.name in ADD_OR_NULL_DATETIME_FUNCTIONS:
                                args.append(f"assumeNotNull(toDateTime({self.visit(arg)}))")
                            else:
                                args.append(f"toDateTime({self.visit(arg)}, 'UTC')")
                        else:
                            args.append(self.visit(arg))
                elif node.name == "concat":
                    args = []
                    for arg in node_args:
                        if isinstance(arg, ast.Constant):
                            if arg.value is None:
                                args.append("''")
                            elif isinstance(arg.value, str):
                                args.append(self.visit(arg))
                            else:
                                args.append(f"toString({self.visit(arg)})")
                        elif isinstance(arg, ast.Call) and arg.name == "toString":
                            if len(arg.args) == 1 and isinstance(arg.args[0], ast.Constant):
                                if arg.args[0].value is None:
                                    args.append("''")
                                else:
                                    args.append(self.visit(arg))
                            else:
                                args.append(f"ifNull({self.visit(arg)}, '')")
                        else:
                            args.append(f"ifNull(toString({self.visit(arg)}), '')")
                else:
                    args = [self.visit(arg) for arg in node_args]

                # Some of these `isinstance` checks are here just to make our type system happy
                # We have some guarantees in place to ensure that the arguments are string/constants anyway
                # Here's to hoping Python's type system gets as smart as TS's one day
                if func_meta.suffix_args:
                    for suffix_arg in func_meta.suffix_args:
                        if len(passthrough_suffix_args) > 0:
                            if not all(isinstance(arg, ast.Constant) for arg in passthrough_suffix_args):
                                raise QueryError(
                                    f"Suffix argument '{suffix_arg.value}' expects ast.Constant arguments, but got {', '.join([type(arg).__name__ for arg in passthrough_suffix_args])}"
                                )

                            suffix_arg_args_values = [
                                arg.value for arg in passthrough_suffix_args if isinstance(arg, ast.Constant)
                            ]

                            if isinstance(suffix_arg.value, str):
                                suffix_arg.value = suffix_arg.value.format(*suffix_arg_args_values)
                            else:
                                raise QueryError(
                                    f"Suffix argument '{suffix_arg.value}' expects a string, but got {type(suffix_arg.value).__name__}"
                                )
                        args.append(self.visit(suffix_arg))

                relevant_clickhouse_name = func_meta.clickhouse_name
                if func_meta.overloads:
                    first_arg_constant_type = (
                        node.args[0].type.resolve_constant_type(self.context)
                        if len(node.args) > 0 and node.args[0].type is not None
                        else None
                    )

                    if first_arg_constant_type is not None:
                        for (
                            overload_types,
                            overload_clickhouse_name,
                        ) in func_meta.overloads:
                            if isinstance(first_arg_constant_type, overload_types):
                                relevant_clickhouse_name = overload_clickhouse_name
                                break  # Found an overload matching the first function org

                if func_meta.tz_aware:
                    has_tz_override = len(node.args) == func_meta.max_args

                    if not has_tz_override:
                        args.append(self.visit(ast.Constant(value=self._get_timezone())))

                    # If the datetime is in correct format, use optimal toDateTime, it's stricter but faster
                    # and it allows CH to use index efficiently.
                    if (
                        relevant_clickhouse_name == "parseDateTime64BestEffortOrNull"
                        and len(node.args) == 1
                        and isinstance(node.args[0], Constant)
                        and isinstance(node.args[0].type, StringType)
                    ):
                        relevant_clickhouse_name = "parseDateTime64BestEffort"
                        pattern_with_microseconds_str = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}$"
                        pattern_mysql_str = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
                        if re.match(pattern_with_microseconds_str, node.args[0].value):
                            relevant_clickhouse_name = "toDateTime64"
                        elif re.match(pattern_mysql_str, node.args[0].value) or re.match(
                            r"^\d{4}-\d{2}-\d{2}$", node.args[0].value
                        ):
                            relevant_clickhouse_name = "toDateTime"
                    if (
                        relevant_clickhouse_name == "now64"
                        and (len(node.args) == 0 or (has_tz_override and len(node.args) == 1))
                    ) or (
                        relevant_clickhouse_name
                        in (
                            "parseDateTime64BestEffortOrNull",
                            "parseDateTime64BestEffortUSOrNull",
                            "parseDateTime64BestEffort",
                            "toDateTime64",
                        )
                        and (len(node.args) == 1 or (has_tz_override and len(node.args) == 2))
                    ):
                        # These two CH functions require a precision argument before timezone
                        args = [*args[:-1], "6", *args[-1:]]

                if node.name == "toStartOfWeek" and len(node.args) == 1:
                    # If week mode hasn't been specified, use the project's default.
                    # For Monday-based weeks mode 3 is used (which is ISO 8601), for Sunday-based mode 0 (CH default)
                    args.insert(1, WeekStartDay(self._get_week_start_day()).clickhouse_mode)

                if node.name == "trimLeft" and len(args) == 2:
                    return f"trim(LEADING {args[1]} FROM {args[0]})"
                elif node.name == "trimRight" and len(args) == 2:
                    return f"trim(TRAILING {args[1]} FROM {args[0]})"
                elif node.name == "trim" and len(args) == 2:
                    return f"trim(BOTH {args[1]} FROM {args[0]})"

                params = [self.visit(param) for param in node.params] if node.params is not None else None
                params_part = f"({', '.join(params)})" if params is not None else ""
                args_part = f"({', '.join(args)})"
                return f"{relevant_clickhouse_name}{params_part}{args_part}"
            else:
                return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"
        elif func_meta := find_hogql_posthog_function(node.name):
            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
            )

            args = [self.visit(arg) for arg in node.args]

            if self.dialect == "clickhouse":
                if node.name == "embedText":
                    return self.visit_constant(resolve_embed_text(self.context.team, node))
                elif node.name == "lookupDomainType":
                    channel_dict = get_channel_definition_dict()
                    return f"coalesce(dictGetOrNull('{channel_dict}', 'domain_type', (coalesce({args[0]}, ''), 'source')), dictGetOrNull('{channel_dict}', 'domain_type', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
                elif node.name == "lookupPaidSourceType":
                    channel_dict = get_channel_definition_dict()
                    return f"coalesce(dictGetOrNull('{channel_dict}', 'type_if_paid', (coalesce({args[0]}, ''), 'source')) , dictGetOrNull('{channel_dict}', 'type_if_paid', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
                elif node.name == "lookupPaidMediumType":
                    channel_dict = get_channel_definition_dict()
                    return f"dictGetOrNull('{channel_dict}', 'type_if_paid', (coalesce({args[0]}, ''), 'medium'))"
                elif node.name == "lookupOrganicSourceType":
                    channel_dict = get_channel_definition_dict()
                    return f"coalesce(dictGetOrNull('{channel_dict}', 'type_if_organic', (coalesce({args[0]}, ''), 'source')), dictGetOrNull('{channel_dict}', 'type_if_organic', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
                elif node.name == "lookupOrganicMediumType":
                    channel_dict = get_channel_definition_dict()
                    return f"dictGetOrNull('{channel_dict}', 'type_if_organic', (coalesce({args[0]}, ''), 'medium'))"
                elif node.name == "convertCurrency":
                    # convertCurrency(from_currency, to_currency, amount, timestamp?)
                    from_currency, to_currency, amount, *_rest = args
                    date = args[3] if len(args) > 3 and args[3] else "today()"
                    db = django_settings.CLICKHOUSE_DATABASE
                    return f"if(equals({from_currency}, {to_currency}), toDecimal64({amount}, 10), if(dictGetOrDefault(`{db}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', {from_currency}, {date}, toDecimal64(0, 10)) = 0, toDecimal64(0, 10), multiplyDecimal(divideDecimal(toDecimal64({amount}, 10), dictGetOrDefault(`{db}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', {from_currency}, {date}, toDecimal64(0, 10))), dictGetOrDefault(`{db}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', {to_currency}, {date}, toDecimal64(0, 10)))))"
                elif node.name == "getSurveyResponse":
                    question_index_obj = node.args[0]
                    if not isinstance(question_index_obj, ast.Constant):
                        raise QueryError("getSurveyResponse first argument must be a constant")
                    if (
                        not isinstance(question_index_obj.value, int | str)
                        or not str(question_index_obj.value).lstrip("-").isdigit()
                    ):
                        raise QueryError("getSurveyResponse first argument must be a valid integer")
                    second_arg = node.args[1] if len(node.args) > 1 else None
                    third_arg = node.args[2] if len(node.args) > 2 else None
                    question_id = str(second_arg.value) if isinstance(second_arg, ast.Constant) else None
                    is_multiple_choice = bool(third_arg.value) if isinstance(third_arg, ast.Constant) else False
                    return get_survey_response_clickhouse_query(
                        int(question_index_obj.value), question_id, is_multiple_choice
                    )

                elif node.name == "uniqueSurveySubmissionsFilter":
                    survey_id = node.args[0]
                    if not isinstance(survey_id, ast.Constant):
                        raise QueryError("uniqueSurveySubmissionsFilter first argument must be a constant")
                    return filter_survey_sent_events_by_unique_submission(survey_id.value, self.context.team_id)

                relevant_clickhouse_name = func_meta.clickhouse_name
                if "{}" in relevant_clickhouse_name:
                    if len(args) != 1:
                        raise QueryError(f"Function '{node.name}' requires exactly one argument")
                    return relevant_clickhouse_name.format(args[0])

                params = [self.visit(param) for param in node.params] if node.params is not None else None
                params_part = f"({', '.join(params)})" if params is not None else ""
                args_part = f"({', '.join(args)})"
                return f"{relevant_clickhouse_name}{params_part}{args_part}"

            # If hogql dialect, just keep it as is
            return f"{node.name}({', '.join(args)})"
        else:
            close_matches = get_close_matches(node.name, ALL_EXPOSED_FUNCTION_NAMES, 1)
            if len(close_matches) > 0:
                raise QueryError(
                    f"Unsupported function call '{node.name}(...)'. Perhaps you meant '{close_matches[0]}(...)'?"
                )
            raise QueryError(f"Unsupported function call '{node.name}(...)'")

    def visit_placeholder(self, node: ast.Placeholder):
        if node.field is None:
            raise QueryError("You can not use placeholders here")
        raise QueryError(f"Unresolved placeholder: {{{node.field}}}")

    def visit_alias(self, node: ast.Alias):
        # Skip hidden aliases completely.
        if node.hidden:
            return self.visit(node.expr)
        expr = node.expr
        while isinstance(expr, ast.Alias) and expr.hidden:
            expr = expr.expr
        inside = self.visit(expr)
        if isinstance(expr, ast.Alias):
            inside = f"({inside})"
        alias = self._print_identifier(node.alias)
        return f"{inside} AS {alias}"

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_hogql()

    def visit_table_alias_type(self, type: ast.TableAliasType):
        return self._print_identifier(type.alias)

    def visit_lambda_argument_type(self, type: ast.LambdaArgumentType):
        return self._print_identifier(type.name)

    def visit_field_type(self, type: ast.FieldType):
        try:
            last_select = self._last_select()
            type_with_name_in_scope = (
                lookup_field_by_name(last_select.type, type.name, self.context) if last_select else None
            )
        except ResolutionError:
            type_with_name_in_scope = None

        if (
            isinstance(type.table_type, ast.TableType)
            or isinstance(type.table_type, ast.TableAliasType)
            or isinstance(type.table_type, ast.VirtualTableType)
        ):
            resolved_field = type.resolve_database_field(self.context)
            if resolved_field is None:
                raise QueryError(f'Can\'t resolve field "{type.name}" on table.')
            if isinstance(resolved_field, Table):
                if isinstance(type.table_type, ast.VirtualTableType):
                    return self.visit(ast.AsteriskType(table_type=ast.TableType(table=resolved_field)))
                else:
                    return self.visit(
                        ast.AsteriskType(
                            table_type=ast.TableAliasType(
                                table_type=ast.TableType(table=resolved_field),
                                alias=type.table_type.alias,
                            )
                        )
                    )

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if (
                self.context.within_non_hogql_query
                and isinstance(type.table_type, ast.VirtualTableType)
                and type.name == "properties"
                and type.table_type.field == "poe"
            ):
                if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"
            else:
                # this errors because resolved_field is of type ast.Alias and not a field - what's the best way to solve?
                field_sql = self._print_identifier(resolved_field.name)
                if self.context.within_non_hogql_query and type_with_name_in_scope == type:
                    # Do not prepend table name in non-hogql context. We don't know what it actually is.
                    return field_sql
                field_sql = f"{self.visit(type.table_type)}.{field_sql}"

        elif (
            isinstance(type.table_type, ast.SelectQueryType)
            or isinstance(type.table_type, ast.SelectQueryAliasType)
            or isinstance(type.table_type, ast.SelectViewType)
            or isinstance(type.table_type, ast.SelectSetQueryType)
        ):
            field_sql = self._print_identifier(type.name)
            if isinstance(type.table_type, ast.SelectQueryAliasType) or isinstance(type.table_type, ast.SelectViewType):
                field_sql = f"{self.visit(type.table_type)}.{field_sql}"

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.within_non_hogql_query and field_sql == "events__pdi__person.properties":
                if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"

        else:
            error = f"Can't access field '{type.name}' on a table with type '{type.table_type.__class__.__name__}'."
            if isinstance(type.table_type, ast.LazyJoinType):
                error += f" Lazy joins should have all been replaced in the resolver."
            raise ImpossibleASTError(error)

        return field_sql

    def _get_materialized_property_source_for_property_type(
        self, type: ast.PropertyType
    ) -> PrintableMaterializedColumn | PrintableMaterializedPropertyGroupItem | None:
        """
        Find the most efficient materialized property source for the provided property type.
        """
        for source in self._get_all_materialized_property_sources(type.field_type, str(type.chain[0])):
            return source
        return None

    def _get_all_materialized_property_sources(
        self, field_type: ast.FieldType, property_name: str
    ) -> Iterable[PrintableMaterializedColumn | PrintableMaterializedPropertyGroupItem]:
        """
        Find all materialized property sources for the provided field type and property name, ordered from what is
        likely to be the most efficient access path to the least efficient.
        """
        # TODO: It likely makes sense to make this independent of whether or not property groups are used.
        if self.context.modifiers.materializationMode == "disabled":
            return

        field = field_type.resolve_database_field(self.context)

        # check for a materialised column
        table = field_type.table_type
        while isinstance(table, ast.TableAliasType) or isinstance(table, ast.VirtualTableType):
            table = table.table_type

        if isinstance(table, ast.TableType):
            if self.dialect == "clickhouse":
                table_name = table.table.to_printed_clickhouse(self.context)
            else:
                table_name = table.table.to_printed_hogql()
            if field is None:
                raise QueryError(f"Can't resolve field {field_type.name} on table {table_name}")
            field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

            materialized_column = self._get_materialized_column(table_name, property_name, field_name)
            if materialized_column is not None:
                yield PrintableMaterializedColumn(
                    self.visit(field_type.table_type),
                    self._print_identifier(materialized_column.name),
                    is_nullable=materialized_column.is_nullable,
                )

            # Check for dmat (dynamic materialized) columns
            if dmat_column := self._get_dmat_column(table_name, field_name, property_name):
                yield PrintableMaterializedColumn(
                    self.visit(field_type.table_type),
                    self._print_identifier(dmat_column),
                    is_nullable=True,
                )

            if self.dialect == "clickhouse" and self.context.modifiers.propertyGroupsMode in (
                PropertyGroupsMode.ENABLED,
                PropertyGroupsMode.OPTIMIZED,
            ):
                # For now, we're assuming that properties are in either no groups or one group, so just using the
                # first group returned is fine. If we start putting properties in multiple groups, this should be
                # revisited to find the optimal set (i.e. smallest set) of groups to read from.
                for property_group_column in property_groups.get_property_group_columns(
                    table_name, field_name, property_name
                ):
                    yield PrintableMaterializedPropertyGroupItem(
                        self.visit(field_type.table_type),
                        self._print_identifier(property_group_column),
                        self.context.add_value(property_name),
                    )
        elif self.context.within_non_hogql_query and (
            isinstance(table, ast.SelectQueryAliasType) and table.alias == "events__pdi__person"
        ):
            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
                materialized_column = self._get_materialized_column("events", property_name, "person_properties")
            else:
                materialized_column = self._get_materialized_column("person", property_name, "properties")
            if materialized_column is not None:
                yield PrintableMaterializedColumn(
                    None,
                    self._print_identifier(materialized_column.name),
                    is_nullable=materialized_column.is_nullable,
                )

    def visit_property_type(self, type: ast.PropertyType):
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return f"{self._print_identifier(type.joined_subquery.alias)}.{self._print_identifier(type.joined_subquery_field_name)}"

        materialized_property_source = self._get_materialized_property_source_for_property_type(type)
        if materialized_property_source is not None:
            # Special handling for $ai_trace_id, $ai_session_id, and $ai_is_error to avoid nullIf wrapping for index optimization
            if (
                len(type.chain) == 1
                and type.chain[0] in ("$ai_trace_id", "$ai_session_id", "$ai_is_error")
                and isinstance(materialized_property_source, PrintableMaterializedColumn)
            ):
                materialized_property_sql = str(materialized_property_source)
            elif (
                isinstance(materialized_property_source, PrintableMaterializedColumn)
                and not materialized_property_source.is_nullable
            ):
                # TODO: rematerialize all columns to properly support empty strings and "null" string values.
                if self.context.modifiers.materializationMode == MaterializationMode.LEGACY_NULL_AS_STRING:
                    materialized_property_sql = f"nullIf({materialized_property_source}, '')"
                else:  # MaterializationMode AUTO or LEGACY_NULL_AS_NULL
                    materialized_property_sql = f"nullIf(nullIf({materialized_property_source}, ''), 'null')"
            else:
                materialized_property_sql = str(materialized_property_source)

            if len(type.chain) == 1:
                return materialized_property_sql
            else:
                return self._unsafe_json_extract_trim_quotes(
                    materialized_property_sql,
                    self._json_property_args(type.chain[1:]),
                )

        return self._unsafe_json_extract_trim_quotes(self.visit(type.field_type), self._json_property_args(type.chain))

    def visit_sample_expr(self, node: ast.SampleExpr) -> Optional[str]:
        # SAMPLE 1 means no sampling, skip it entirely
        if node.sample_value.left.value == 1 and node.sample_value.right is None and node.offset_value is None:
            return None

        sample_value = self.visit_ratio_expr(node.sample_value)
        offset_clause = ""
        if node.offset_value:
            offset_value = self.visit_ratio_expr(node.offset_value)
            offset_clause = f" OFFSET {offset_value}"

        return f"SAMPLE {sample_value}{offset_clause}"

    def visit_ratio_expr(self, node: ast.RatioExpr):
        return self.visit(node.left) if node.right is None else f"{self.visit(node.left)}/{self.visit(node.right)}"

    def visit_select_query_alias_type(self, type: ast.SelectQueryAliasType):
        return self._print_identifier(type.alias)

    def visit_select_view_type(self, type: ast.SelectViewType):
        return self._print_identifier(type.alias)

    def visit_field_alias_type(self, type: ast.FieldAliasType):
        return self._print_identifier(type.alias)

    def visit_virtual_table_type(self, type: ast.VirtualTableType):
        return self.visit(type.table_type)

    def visit_asterisk_type(self, type: ast.AsteriskType):
        return "*"

    def visit_lazy_join_type(self, type: ast.LazyJoinType):
        raise ImpossibleASTError("Unexpected ast.LazyJoinType. Make sure LazyJoinResolver has run on the AST.")

    def visit_lazy_table_type(self, type: ast.LazyJoinType):
        raise ImpossibleASTError("Unexpected ast.LazyTableType. Make sure LazyJoinResolver has run on the AST.")

    def visit_field_traverser_type(self, type: ast.FieldTraverserType):
        raise ImpossibleASTError("Unexpected ast.FieldTraverserType. This should have been resolved.")

    def visit_unresolved_field_type(self, type: ast.UnresolvedFieldType):
        return self._print_identifier(type.name)

    def visit_unknown(self, node: AST):
        raise ImpossibleASTError(f"Unknown AST node {type(node).__name__}")

    def visit_window_expr(self, node: ast.WindowExpr):
        strings: list[str] = []
        if node.partition_by is not None:
            if len(node.partition_by) == 0:
                raise ImpossibleASTError("PARTITION BY must have at least one argument")
            strings.append("PARTITION BY")
            columns = []
            for expr in node.partition_by:
                columns.append(self.visit(expr))
            strings.append(", ".join(columns))

        if node.order_by is not None:
            if len(node.order_by) == 0:
                raise ImpossibleASTError("ORDER BY must have at least one argument")
            strings.append("ORDER BY")
            columns = []
            for expr in node.order_by:
                columns.append(self.visit(expr))
            strings.append(", ".join(columns))

        if node.frame_method is not None:
            if node.frame_method == "ROWS":
                strings.append("ROWS")
            elif node.frame_method == "RANGE":
                strings.append("RANGE")
            else:
                raise ImpossibleASTError(f"Invalid frame method {node.frame_method}")
            if node.frame_start and node.frame_end is None:
                strings.append(self.visit(node.frame_start))
            elif node.frame_start is not None and node.frame_end is not None:
                strings.append("BETWEEN")
                strings.append(self.visit(node.frame_start))
                strings.append("AND")
                strings.append(self.visit(node.frame_end))
            else:
                raise ImpossibleASTError("Frame start and end must be specified together")
        return " ".join(strings)

    def visit_window_function(self, node: ast.WindowFunction):
        identifier = self._print_identifier(node.name)
        exprs = [self.visit(expr) for expr in node.exprs or []]
        cloned_node = cast(ast.WindowFunction, clone_expr(node))

        # For compatibility with ClickHouse syntax, convert lag/lead to lagInFrame/leadInFrame and add default window frame if needed
        if identifier in ("lag", "lead") and self.dialect != "postgres":
            identifier = f"{identifier}InFrame"
            # Wrap the first expression (value) and third expression (default) in toNullable()
            # The second expression (offset) must remain a non-nullable integer
            if len(exprs) > 0:
                exprs[0] = f"toNullable({exprs[0]})"  # value
            # If there's no window frame specified, add the default one
            if not cloned_node.over_expr and not cloned_node.over_identifier:
                cloned_node.over_expr = self._create_default_window_frame(cloned_node)
            # If there's an over_identifier, we need to extract the new window expr just for this function
            elif cloned_node.over_identifier:
                # Find the last select query to look up the window definition
                last_select = self._last_select()
                if last_select and last_select.window_exprs and cloned_node.over_identifier in last_select.window_exprs:
                    base_window = last_select.window_exprs[cloned_node.over_identifier]
                    # Create a new window expr based on the referenced one
                    cloned_node.over_expr = ast.WindowExpr(
                        partition_by=base_window.partition_by,
                        order_by=base_window.order_by,
                        frame_method="ROWS" if not base_window.frame_method else base_window.frame_method,
                        frame_start=base_window.frame_start
                        or ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                        frame_end=base_window.frame_end
                        or ast.WindowFrameExpr(frame_type="FOLLOWING", frame_value=None),
                    )
                    cloned_node.over_identifier = None
            # If there's an ORDER BY but no frame, add the default frame
            elif cloned_node.over_expr and cloned_node.over_expr.order_by and not cloned_node.over_expr.frame_method:
                cloned_node.over_expr = self._create_default_window_frame(cloned_node)

        # Handle any additional function arguments
        args = f"({', '.join(self.visit(arg) for arg in cloned_node.args)})" if cloned_node.args else ""

        if cloned_node.over_expr or cloned_node.over_identifier:
            over = (
                f"({self.visit(cloned_node.over_expr)})"
                if cloned_node.over_expr
                else self._print_identifier(cloned_node.over_identifier)
            )
        else:
            over = "()"

        # Handle the case where we have both regular expressions and function arguments
        if cloned_node.args:
            return f"{identifier}({', '.join(exprs)}){args} OVER {over}"
        else:
            return f"{identifier}({', '.join(exprs)}) OVER {over}"

    def visit_window_frame_expr(self, node: ast.WindowFrameExpr):
        if node.frame_type == "PRECEDING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} PRECEDING"
        elif node.frame_type == "FOLLOWING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} FOLLOWING"
        elif node.frame_type == "CURRENT ROW":
            return "CURRENT ROW"
        else:
            raise ImpossibleASTError(f"Invalid frame type {node.frame_type}")

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        attributes = []
        children = []
        for attribute in node.attributes:
            if isinstance(attribute, ast.HogQLXAttribute) and attribute.name == "children":
                if isinstance(attribute.value, list):
                    children.extend(attribute.value)
                else:
                    children.append(attribute.value)
            else:
                attributes.append(attribute)

        tag = f"<{self._print_identifier(node.kind)}"
        if attributes:
            tag += " " + (" ".join(self.visit(a) for a in attributes))
        if children:
            children_contents = [
                self.visit(child) if isinstance(child, ast.HogQLXTag) else "{" + self.visit(child) + "}"
                for child in children
            ]
            tag += ">" + ("".join(children_contents)) + "</" + self._print_identifier(node.kind) + ">"
        else:
            tag += " />"

        return tag

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        if isinstance(node.value, ast.HogQLXTag):
            value = self.visit(node.value)
        elif isinstance(node.value, list):
            value = "{[" + (", ".join(self.visit(x) for x in node.value)) + "]}"
        else:
            value = "{" + self.visit(node.value) + "}"
        return f"{self._print_identifier(node.name)}={value}"

    def _last_select(self) -> ast.SelectQuery | None:
        """Find the last SELECT query in the stack."""
        for node in reversed(self.stack):
            if isinstance(node, ast.SelectQuery):
                return node
        return None

    def _print_identifier(self, name: str) -> str:
        if self.dialect == "postgres":
            return escape_postgres_identifier(name)
        else:
            return escape_hogql_identifier(name)

    def _print_hogql_identifier_or_index(self, name: str | int) -> str:
        # Regular identifiers can't start with a number. Print digit strings as-is for unescaped tuple access.
        if isinstance(name, int) and str(name).isdigit():
            return str(name)
        return escape_hogql_identifier(name)

    def _print_escaped_string(
        self, name: float | int | str | list | tuple | datetime | date | UUID | UUIDT | None
    ) -> str:
        return escape_hogql_string(name, timezone=self._get_timezone())

    def _unsafe_json_extract_trim_quotes(self, unsafe_field: str, unsafe_args: list[str]) -> str:
        if self.dialect == "postgres":
            if len(unsafe_args) == 0:
                return unsafe_field

            json_expr = unsafe_field
            for arg in unsafe_args[:-1]:
                json_expr = f"({json_expr}) -> {arg}"

            return f"({json_expr}) ->> {unsafe_args[-1]}"

        return f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw({', '.join([unsafe_field, *unsafe_args])}), ''), 'null'), '^\"|\"$', '')"

    def _json_property_args(self, chain: list[str]) -> list[str]:
        if self.dialect == "postgres":
            return [self._print_escaped_string(name) for name in chain]

        return [self.context.add_value(name) for name in chain]

    def _get_materialized_column(
        self, table_name: str, property_name: PropertyName, field_name: TableColumn
    ) -> MaterializedColumn | None:
        return get_materialized_column_for_property(
            cast(TablesWithMaterializedColumns, table_name), field_name, property_name
        )

    def _get_dmat_column(self, table_name: str, field_name: str, property_name: str) -> str | None:
        """
        Get the dmat column name for a property if available.

        Returns the column name (e.g., 'dmat_numeric_3') if a materialized slot exists,
        otherwise None.
        """
        if self.context.property_swapper is None:
            return None

        # Only event properties have dmat columns
        if table_name != "events" or field_name != "properties":
            return None

        prop_info = self.context.property_swapper.event_properties.get(property_name)
        if prop_info:
            return prop_info.get("dmat")

        return None

    def _get_timezone(self) -> str:
        if self.context.modifiers.convertToProjectTimezone is False:
            return "UTC"
        return self.context.database.get_timezone() if self.context.database else "UTC"

    def _get_week_start_day(self) -> WeekStartDay:
        return self.context.database.get_week_start_day() if self.context.database else WeekStartDay.SUNDAY

    def _is_type_nullable(self, node_type: ast.Type) -> bool | None:
        if isinstance(node_type, ast.PropertyType):
            return True
        elif isinstance(node_type, ast.ConstantType):
            return node_type.nullable
        elif isinstance(node_type, ast.CallType):
            return node_type.return_type.nullable
        elif isinstance(node_type, ast.FieldType):
            return node_type.is_nullable(self.context)
        return None

    def _is_nullable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value is None
        elif node.type and (nullable := self._is_type_nullable(node.type)) is not None:
            return nullable
        elif isinstance(node, ast.Alias):
            return self._is_nullable(node.expr)
        elif (
            isinstance(node.type, ast.FieldAliasType)
            and (field_type := resolve_field_type(node))
            and (nullable := self._is_type_nullable(field_type)) is not None
        ):
            return nullable
        return True

    def _print_settings(self, settings):
        pairs = []
        for key, value in settings:
            if value is None:
                continue
            if not isinstance(value, int | float | str):
                raise QueryError(f"Setting {key} must be a string, int, or float")
            if not re.match(r"^[a-zA-Z0-9_]+$", key):
                raise QueryError(f"Setting {key} is not supported")
            if isinstance(value, bool):
                pairs.append(f"{key}={1 if value else 0}")
            elif isinstance(value, int) or isinstance(value, float):
                pairs.append(f"{key}={value}")
            else:
                pairs.append(f"{key}={self._print_escaped_string(value)}")
        if len(pairs) > 0:
            return f"SETTINGS {', '.join(pairs)}"
        return None

    def _create_default_window_frame(self, node: ast.WindowFunction):
        # For lag/lead functions, we need to order by the first argument by default
        order_by: list[ast.OrderExpr] | None = None
        if node.over_expr and node.over_expr.order_by:
            order_by = [cast(ast.OrderExpr, clone_expr(expr)) for expr in node.over_expr.order_by]
        elif node.exprs is not None and len(node.exprs) > 0:
            order_by = [ast.OrderExpr(expr=clone_expr(node.exprs[0]), order="ASC")]

        # Preserve existing PARTITION BY if provided via an existing OVER () clause
        partition_by: list[ast.Expr] | None = None
        if node.over_expr and node.over_expr.partition_by:
            partition_by = [cast(ast.Expr, clone_expr(expr)) for expr in node.over_expr.partition_by]

        return ast.WindowExpr(
            partition_by=partition_by,
            order_by=order_by,
            frame_method="ROWS",
            frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
            frame_end=ast.WindowFrameExpr(frame_type="FOLLOWING", frame_value=None),
        )


class PostgresPrinter(_Printer):
    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["postgres"],
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty)

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(node.chain)}")

        return self.visit(node.type)

    def visit_call(self, node: ast.Call):
        # No function call validation for postgres
        args = [self.visit(arg) for arg in node.args]

        if node.name.lower() in ["and", "or"]:
            if len(args) == 0:
                return f"{node.name}()"
            if len(args) == 1:
                return args[0]

            operator = "AND" if node.name.lower() == "and" else "OR"
            joined_args = f" {operator} ".join(args)
            return f"({joined_args})"

        return f"{node.name}({', '.join(args)})"

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_postgres()

    def _visit_in_values(self, node: ast.Expr) -> str:
        if isinstance(node, ast.Tuple):
            return f"({', '.join(self.visit(value) for value in node.exprs)})"

        return self.visit(node)

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)

        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            right = self._visit_in_values(node.right)
        else:
            right = self.visit(node.right)

        return self._get_compare_op(node.op, left, right)

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Eq:
            return f"({left} = {right})"
        elif op == ast.CompareOperationOp.NotEq:
            return f"({left} != {right})"
        elif op == ast.CompareOperationOp.Like:
            return f"({left} LIKE {right})"
        elif op == ast.CompareOperationOp.NotLike:
            return f"({left} NOT LIKE {right})"
        elif op == ast.CompareOperationOp.ILike:
            return f"({left} ILIKE {right})"
        elif op == ast.CompareOperationOp.NotILike:
            return f"({left} NOT ILIKE {right})"
        elif op == ast.CompareOperationOp.In:
            return f"({left} IN {right})"
        elif op == ast.CompareOperationOp.NotIn:
            return f"({left} NOT IN {right})"
        # elif op == ast.CompareOperationOp.Regex:
        #     return f"match({left}, {right})"
        # elif op == ast.CompareOperationOp.NotRegex:
        #     return f"not(match({left}, {right}))"
        # elif op == ast.CompareOperationOp.IRegex:
        #     return f"match({left}, concat('(?i)', {right}))"
        # elif op == ast.CompareOperationOp.NotIRegex:
        #     return f"not(match({left}, concat('(?i)', {right})))"
        elif op == ast.CompareOperationOp.Gt:
            return f"({left} > {right})"
        elif op == ast.CompareOperationOp.GtEq:
            return f"({left} >= {right})"
        elif op == ast.CompareOperationOp.Lt:
            return f"({left} < {right})"
        elif op == ast.CompareOperationOp.LtEq:
            return f"({left} <= {right})"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {op.name}")


class ClickHousePrinter(_Printer):
    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["clickhouse"],
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty)

    def visit(self, node: AST | None):
        if node is None:
            return ""
        response = super().visit(node)

        if len(self.stack) == 0 and self.settings:
            if not isinstance(node, ast.SelectQuery) and not isinstance(node, ast.SelectSetQuery):
                raise QueryError("Settings can only be applied to SELECT queries")
            settings = self._print_settings(self.settings)
            if settings is not None:
                response += " " + settings

        return response

    def visit_select_query(self, node: ast.SelectQuery):
        if not self.context.enable_select_queries:
            raise InternalHogQLError("Full SELECT queries are disabled if context.enable_select_queries is False")
        if not self.context.team_id:
            raise InternalHogQLError("Full SELECT queries are disabled if context.team_id is not set")

        return super().visit_select_query(node)

    def visit_and(self, node: ast.And):
        """
        optimizations:
        1. and(expr0, 1, expr2, ...) <=> and(expr0, expr2, ...)
        2. and(expr0, 0, expr2, ...) <=> 0
        """
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        exprs: list[str] = []
        for expr in node.exprs:
            printed = self.visit(expr)
            if printed == "0":  # optimization 2
                return "0"
            if printed != "1":  # optimization 1
                exprs.append(printed)
        if len(exprs) == 0:
            return "1"
        elif len(exprs) == 1:
            return exprs[0]
        return f"and({', '.join(exprs)})"

    def visit_or(self, node: ast.Or):
        """
        optimizations:
        1. or(expr0, 1, expr2, ...) <=> 1
        2. or(expr0, 0, expr2, ...) <=> or(expr0, expr2, ...)
        """
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        exprs: list[str] = []
        for expr in node.exprs:
            printed = self.visit(expr)
            if printed == "1":
                return "1"
            if printed != "0":
                exprs.append(printed)
        if len(exprs) == 0:
            return "0"
        elif len(exprs) == 1:
            return exprs[0]
        return f"or({', '.join(exprs)})"

    def visit_between_expr(self, node: ast.BetweenExpr):
        op = super().visit_between_expr(node)

        nullable_expr = self._is_nullable(node.expr)
        nullable_low = self._is_nullable(node.low)
        nullable_high = self._is_nullable(node.high)
        not_nullable = not nullable_expr and not nullable_low and not nullable_high

        if not_nullable:
            return op

        return f"ifNull({op}, 0)"

    def visit_constant(self, node: ast.Constant):
        if (
            node.value is None
            or isinstance(node.value, bool)
            or isinstance(node.value, int)
            or isinstance(node.value, float)
            or isinstance(node.value, UUID)
            or isinstance(node.value, UUIDT)
            or isinstance(node.value, datetime)
            or isinstance(node.value, date)
        ):
            # Inline some permitted types in ClickHouse
            value = self._print_escaped_string(node.value)
            if "%" in value:
                # We don't know if this will be passed on as part of a legacy ClickHouse query or not.
                # Ban % to be on the safe side. Who knows how it can end up in a UUID or datetime for example.
                raise QueryError(f"Invalid character '%' in constant: {value}")
            return value
        else:
            # Strings, lists, tuples, and any other random datatype printed in ClickHouse.
            return self.context.add_value(node.value)

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(node.chain)}")

        return self.visit(node.type)

    def _get_property_group_source_for_field(
        self, field_type: ast.FieldType, property_name: str
    ) -> PrintableMaterializedPropertyGroupItem | None:
        """
        Find a property group source for the given field and property name.
        Used for JSONHas optimizations where we specifically need property group sources
        (not mat_* columns) because property groups can efficiently check for key existence.
        """
        if self.dialect != "clickhouse":
            return None

        if self.context.modifiers.propertyGroupsMode not in (
            PropertyGroupsMode.ENABLED,
            PropertyGroupsMode.OPTIMIZED,
        ):
            return None

        field = field_type.resolve_database_field(self.context)
        table = field_type.table_type
        while isinstance(table, ast.TableAliasType) or isinstance(table, ast.VirtualTableType):
            table = table.table_type

        if not isinstance(table, ast.TableType):
            return None

        table_name = table.table.to_printed_clickhouse(self.context)
        if field is None or not isinstance(field, DatabaseField):
            return None
        field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

        for property_group_column in property_groups.get_property_group_columns(table_name, field_name, property_name):
            return PrintableMaterializedPropertyGroupItem(
                self.visit(field_type.table_type),
                self._print_identifier(property_group_column),
                self.context.add_value(property_name),
            )

        return None

    def _get_optimized_property_group_call(self, node: ast.Call) -> str | None:
        """
        Returns a printed expression corresponding to the provided call, if the function is being applied to a property
        group value and the function can be rewritten so that it can be eligible for use by the property group's map's
        key bloom filter index, or can be optimized to avoid reading the property group's map ``values`` subcolumn.
        """
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        # XXX: A lot of this is duplicated (sometimes just copy/pasted) from the null equality comparison logic -- it
        # might make sense to make it so that ``isNull``/``isNotNull`` is rewritten to comparison expressions before
        # this step, similar to how ``equals``/``notEquals`` are interpreted as their comparison operation counterparts.

        match node:
            case ast.Call(name="isNull" | "isNotNull" as function_name, args=[field]):
                # TODO: can probably optimize chained operations, but will need more thought
                field_type = resolve_field_type(field)
                if isinstance(field_type, ast.PropertyType) and len(field_type.chain) == 1:
                    property_source = self._get_materialized_property_source_for_property_type(field_type)
                    if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                        return None

                    match function_name:
                        case "isNull":
                            return f"not({property_source.has_expr})"
                        case "isNotNull":
                            return property_source.has_expr
                        case _:
                            raise ValueError(f"unexpected node name: {function_name}")
            case ast.Call(name="JSONHas", args=[field, ast.Constant(value=property_name)]):
                # TODO: can probably optimize chained operations here as well
                field_type = resolve_field_type(field)
                if not isinstance(field_type, ast.FieldType):
                    return None

                # TRICKY: Materialized property columns do not currently support null values (see comment in
                # `visit_property_type`) so checking whether or not a property is set for a row cannot safely use that
                # field and falls back to the equivalent ``JSONHas(properties, ...)`` call instead. However, if this
                # property is part of *any* property group, we can use that column instead to evaluate this expression
                # more efficiently -- even if the materialized column would be a better choice in other situations.
                if property_source := self._get_property_group_source_for_field(field_type, str(property_name)):
                    return property_source.has_expr

        return None  # nothing to optimize

    def visit_compare_operation(self, node: ast.CompareOperation):
        # If either side of the operation is a property that is part of a property group, special optimizations may
        # apply here to ensure that data skipping indexes can be used when possible.
        if optimized_property_group_compare_operation := self._get_optimized_property_group_compare_operation(node):
            return optimized_property_group_compare_operation

        # If either side is an individually materialized column being compared to a string constant,
        # we can skip the nullIf wrapping to allow skip index usage.
        if optimized_materialized_column_compare := self._get_optimized_materialized_column_compare_operation(node):
            return optimized_materialized_column_compare

        in_join_constraint = any(isinstance(item, ast.JoinConstraint) for item in self.stack)
        left = self.visit(node.left)
        right = self.visit(node.right)
        nullable_left = self._is_nullable(node.left)
        nullable_right = self._is_nullable(node.right)
        not_nullable = not nullable_left and not nullable_right

        # :HACK: until the new type system is out: https://github.com/PostHog/posthog/pull/17267
        # If we add a ifNull() around `events.timestamp`, we lose on the performance of the index.
        if ("toTimeZone(" in left and (".timestamp" in left or "_timestamp" in left)) or (
            "toTimeZone(" in right and (".timestamp" in right or "_timestamp" in right)
        ):
            not_nullable = True
        hack_sessions_timestamp = (
            "fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000))",
            "raw_sessions_v3.session_timestamp",
        )
        if left in hack_sessions_timestamp or right in hack_sessions_timestamp:
            not_nullable = True

        # :HACK: Prevent ifNull() wrapping for $ai_trace_id, $ai_session_id, and $ai_is_error to allow index usage
        # The materialized columns mat_$ai_trace_id, mat_$ai_session_id, and mat_$ai_is_error have bloom filter indexes for performance
        if (
            "mat_$ai_trace_id" in left
            or "mat_$ai_trace_id" in right
            or "mat_$ai_session_id" in left
            or "mat_$ai_session_id" in right
            or "mat_$ai_is_error" in left
            or "mat_$ai_is_error" in right
            or "$ai_trace_id" in left
            or "$ai_trace_id" in right
            or "$ai_session_id" in left
            or "$ai_session_id" in right
            or "$ai_is_error" in left
            or "$ai_is_error" in right
        ):
            not_nullable = True

        constant_lambda = None
        value_if_one_side_is_null = False
        value_if_both_sides_are_null = False

        op = self._get_compare_op(node.op, left, right)
        if node.op == ast.CompareOperationOp.Eq:
            constant_lambda = lambda left_op, right_op: left_op == right_op
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotEq:
            constant_lambda = lambda left_op, right_op: left_op != right_op
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Like:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotLike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.ILike:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotILike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.In:
            return op
        elif node.op == ast.CompareOperationOp.NotIn:
            return op
        elif node.op == ast.CompareOperationOp.GlobalIn:
            pass
        elif node.op == ast.CompareOperationOp.GlobalNotIn:
            pass
        elif node.op == ast.CompareOperationOp.Regex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.IRegex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotIRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Gt:
            constant_lambda = lambda left_op, right_op: (
                left_op > right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.GtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op >= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.Lt:
            constant_lambda = lambda left_op, right_op: (
                left_op < right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.LtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op <= right_op if left_op is not None and right_op is not None else False
            )
        # only used for hogql direct printing (no prepare called)
        elif node.op == ast.CompareOperationOp.InCohort:
            op = f"{left} IN COHORT {right}"
        # only used for hogql direct printing (no prepare called)
        elif node.op == ast.CompareOperationOp.NotInCohort:
            op = f"{left} NOT IN COHORT {right}"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {node.op.name}")

        # Try to see if we can take shortcuts

        # Can we compare constants?
        if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant) and constant_lambda is not None:
            return "1" if constant_lambda(node.left.value, node.right.value) else "0"

        # Special cases when we should not add any null checks
        if in_join_constraint or self.dialect == "hogql" or not_nullable:
            return op

        # Special optimization for "Eq" operator
        if (
            node.op == ast.CompareOperationOp.Eq
            or node.op == ast.CompareOperationOp.Like
            or node.op == ast.CompareOperationOp.ILike
        ):
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNull({left})"
                return f"ifNull({op}, 0)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNull({right})"
                return f"ifNull({op}, 0)"
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate

        # Special optimization for "NotEq" operator
        if (
            node.op == ast.CompareOperationOp.NotEq
            or node.op == ast.CompareOperationOp.NotLike
            or node.op == ast.CompareOperationOp.NotILike
        ):
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNotNull({left})"
                return f"ifNull({op}, 1)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNotNull({right})"
                return f"ifNull({op}, 1)"
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"  # Worse case performance, but accurate

        # Return false if one, but only one of the two sides is a null constant
        if isinstance(node.right, ast.Constant) and node.right.value is None:
            # Both are a constant null
            if isinstance(node.left, ast.Constant) and node.left.value is None:
                return "1" if value_if_both_sides_are_null is True else "0"

            # Only the right side is null. Return a value only if the left side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"
        elif isinstance(node.left, ast.Constant) and node.left.value is None:
            # Only the left side is null. Return a value only if the right side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"

        # No constants, so check for nulls in SQL
        if value_if_one_side_is_null is True and value_if_both_sides_are_null is True:
            return f"ifNull({op}, 1)"
        elif value_if_one_side_is_null is True and value_if_both_sides_are_null is False:
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is True:
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is False:
            return f"ifNull({op}, 0)"
        else:
            raise ImpossibleASTError("Impossible")

    def visit_call(self, node: ast.Call):
        # If the argument(s) are part of a property group, special optimizations may apply here to ensure that data
        # skipping indexes can be used when possible.
        if optimized_property_group_call := self._get_optimized_property_group_call(node):
            return optimized_property_group_call

        return super().visit_call(node)

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        raise QueryError("Printing HogQLX tags is only supported in HogQL queries")

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        raise QueryError("Printing HogQLX tags is only supported in HogQL queries")

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_clickhouse(self.context)

    def visit_unresolved_field_type(self, type: ast.UnresolvedFieldType):
        raise QueryError(f"Unable to resolve field: {type.name}")

    def _print_identifier(self, name: str) -> str:
        return escape_clickhouse_identifier(name)

    def _print_escaped_string(
        self, name: float | int | str | list | tuple | datetime | date | UUID | UUIDT | None
    ) -> str:
        return escape_clickhouse_string(name, timezone=self._get_timezone())
