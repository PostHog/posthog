from dataclasses import dataclass
from typing import List, Literal, Optional, Union, cast

from ee.clickhouse.materialized_columns.columns import TablesWithMaterializedColumns, get_materialized_columns
from posthog.hogql import ast
from posthog.hogql.constants import CLICKHOUSE_FUNCTIONS, HOGQL_AGGREGATIONS, MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database import Table
from posthog.hogql.print_string import print_clickhouse_identifier, print_hogql_identifier
from posthog.hogql.resolver import ResolverException, lookup_field_by_name, resolve_symbols
from posthog.hogql.transforms import expand_asterisks, resolve_lazy_tables
from posthog.hogql.visitor import Visitor
from posthog.models.property import PropertyName, TableColumn


def team_id_guard_for_table(
    table_symbol: Union[ast.TableSymbol, ast.TableAliasSymbol], context: HogQLContext
) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.select_team_id:
        raise ValueError("context.select_team_id not found")

    return ast.CompareOperation(
        op=ast.CompareOperationType.Eq,
        left=ast.Field(chain=["team_id"], symbol=ast.FieldSymbol(name="team_id", table=table_symbol)),
        right=ast.Constant(value=context.select_team_id),
    )


def print_ast(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
) -> str:
    """Print an AST into a string. Does not modify the node."""
    symbol = stack[-1].symbol if stack else None

    # resolve symbols
    resolve_symbols(node, symbol)

    # modify the cloned tree as needed
    if dialect == "clickhouse":
        expand_asterisks(node)
        resolve_lazy_tables(node, stack)
        # TODO: add team_id checks (currently done in the printer)

    return _Printer(context=context, dialect=dialect, stack=stack or []).visit(node)


@dataclass
class JoinExprResponse:
    printed_sql: str
    where: Optional[ast.Expr] = None


class _Printer(Visitor):
    # NOTE: Call "print_ast()", not this class directly.

    def __init__(
        self, context: HogQLContext, dialect: Literal["hogql", "clickhouse"], stack: Optional[List[ast.AST]] = None
    ):
        self.context = context
        self.dialect = dialect
        # Keep track of all traversed nodes.
        self.stack: List[ast.AST] = stack or []

    def visit(self, node: ast.AST):
        self.stack.append(node)
        response = super().visit(node)
        self.stack.pop()
        return response

    def visit_select_query(self, node: ast.SelectQuery):
        if self.dialect == "clickhouse" and not self.context.select_team_id:
            raise ValueError("Full SELECT queries are disabled if context.select_team_id is not set")

        # We will add extra clauses onto this from the joined tables
        where = node.where

        joined_tables = []
        next_join = node.select_from
        while isinstance(next_join, ast.JoinExpr):
            if next_join.symbol is None:
                raise ValueError("Printing queries with a FROM clause is not permitted before symbol resolution")

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
                    where = ast.And(exprs=[extra_where] + where.exprs)
                else:
                    where = ast.And(exprs=[extra_where, where])
            else:
                raise ValueError(f"Invalid where of type {type(extra_where).__name__} returned by join_expr")

            next_join = next_join.next_join

        columns = [self.visit(column) for column in node.select] if node.select else ["1"]
        where = self.visit(where) if where else None
        having = self.visit(node.having) if node.having else None
        prewhere = self.visit(node.prewhere) if node.prewhere else None
        group_by = [self.visit(column) for column in node.group_by] if node.group_by else None
        order_by = [self.visit(column) for column in node.order_by] if node.order_by else None

        clauses = [
            f"SELECT {'DISTINCT ' if node.distinct else ''}{', '.join(columns)}",
            f"FROM {' '.join(joined_tables)}" if len(joined_tables) > 0 else None,
            "PREWHERE " + prewhere if prewhere else None,
            "WHERE " + where if where else None,
            f"GROUP BY {', '.join(group_by)}" if group_by and len(group_by) > 0 else None,
            "HAVING " + having if having else None,
            f"ORDER BY {', '.join(order_by)}" if order_by and len(order_by) > 0 else None,
        ]

        limit = node.limit
        if self.context.limit_top_select and len(self.stack) == 1:
            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, MAX_SELECT_RETURNED_ROWS)
                else:
                    limit = ast.Call(name="min2", args=[ast.Constant(value=MAX_SELECT_RETURNED_ROWS), limit])
            else:
                limit = ast.Constant(value=MAX_SELECT_RETURNED_ROWS)

        if limit is not None:
            clauses.append(f"LIMIT {self.visit(limit)}")
            if node.offset is not None:
                clauses.append(f"OFFSET {self.visit(node.offset)}")
            if node.limit_by is not None:
                clauses.append(f"BY {', '.join([self.visit(expr) for expr in node.limit_by])}")
            if node.limit_with_ties:
                clauses.append("WITH TIES")

        response = " ".join([clause for clause in clauses if clause])

        # If we are printing a SELECT subquery (not the first AST node we are visiting), wrap it in parentheses.
        if len(self.stack) > 1:
            response = f"({response})"

        return response

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        # return constraints we must place on the select query
        extra_where: Optional[ast.Expr] = None

        join_strings = []
        if node.join_type is not None:
            join_strings.append(node.join_type)

        if isinstance(node.symbol, ast.TableAliasSymbol):
            table_symbol = node.symbol.table_symbol
            if table_symbol is None:
                raise ValueError(f"Table alias {node.symbol.name} does not resolve!")
            if not isinstance(table_symbol, ast.TableSymbol):
                raise ValueError(f"Table alias {node.symbol.name} does not resolve to a table!")
            join_strings.append(self._print_identifier(table_symbol.table.clickhouse_table()))
            if node.alias is not None:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")

            if self.dialect == "clickhouse":
                # TODO: do this in a separate pass before printing, along with person joins and other transforms
                extra_where = team_id_guard_for_table(node.symbol, self.context)

        elif isinstance(node.symbol, ast.TableSymbol):
            join_strings.append(self._print_identifier(node.symbol.table.clickhouse_table()))

            if self.dialect == "clickhouse":
                # TODO: do this in a separate pass before printing, along with person joins and other transforms
                extra_where = team_id_guard_for_table(node.symbol, self.context)

        elif isinstance(node.symbol, ast.SelectQuerySymbol):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.symbol, ast.SelectQueryAliasSymbol) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")
        else:
            raise ValueError("Only selecting from a table or a subquery is supported")

        if node.table_final:
            join_strings.append("FINAL")

        if node.constraint is not None:
            join_strings.append(f"ON {self.visit(node.constraint)}")

        return JoinExprResponse(printed_sql=" ".join(join_strings), where=extra_where)

    def visit_binary_operation(self, node: ast.BinaryOperation):
        if node.op == ast.BinaryOperationType.Add:
            return f"plus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.BinaryOperationType.Sub:
            return f"minus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.BinaryOperationType.Mult:
            return f"multiply({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.BinaryOperationType.Div:
            return f"divide({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.BinaryOperationType.Mod:
            return f"modulo({self.visit(node.left)}, {self.visit(node.right)})"
        else:
            raise ValueError(f"Unknown BinaryOperationType {node.op}")

    def visit_and(self, node: ast.And):
        return f"and({', '.join([self.visit(operand) for operand in node.exprs])})"

    def visit_or(self, node: ast.Or):
        return f"or({', '.join([self.visit(operand) for operand in node.exprs])})"

    def visit_not(self, node: ast.Not):
        return f"not({self.visit(node.expr)})"

    def visit_order_expr(self, node: ast.OrderExpr):
        return f"{self.visit(node.expr)} {node.order}"

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)
        right = self.visit(node.right)
        if node.op == ast.CompareOperationType.Eq:
            if isinstance(node.right, ast.Constant) and node.right.value is None:
                return f"isNull({left})"
            else:
                return f"equals({left}, {right})"
        elif node.op == ast.CompareOperationType.NotEq:
            if isinstance(node.right, ast.Constant) and node.right.value is None:
                return f"isNotNull({left})"
            else:
                return f"notEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Gt:
            return f"greater({left}, {right})"
        elif node.op == ast.CompareOperationType.GtE:
            return f"greaterOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Lt:
            return f"less({left}, {right})"
        elif node.op == ast.CompareOperationType.LtE:
            return f"lessOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Like:
            return f"like({left}, {right})"
        elif node.op == ast.CompareOperationType.ILike:
            return f"ilike({left}, {right})"
        elif node.op == ast.CompareOperationType.NotLike:
            return f"not(like({left}, {right}))"
        elif node.op == ast.CompareOperationType.NotILike:
            return f"not(ilike({left}, {right}))"
        elif node.op == ast.CompareOperationType.In:
            return f"in({left}, {right})"
        elif node.op == ast.CompareOperationType.NotIn:
            return f"not(in({left}, {right}))"
        elif node.op == ast.CompareOperationType.Regex:
            return f"match({left}, {right})"
        elif node.op == ast.CompareOperationType.NotRegex:
            return f"not(match({left}, {right}))"
        else:
            raise ValueError(f"Unknown CompareOperationType: {type(node.op).__name__}")

    def visit_constant(self, node: ast.Constant):
        key = f"hogql_val_{len(self.context.values)}"
        if isinstance(node.value, bool) and node.value is True:
            return "true"
        elif isinstance(node.value, bool) and node.value is False:
            return "false"
        elif isinstance(node.value, int) or isinstance(node.value, float):
            # :WATCH_OUT: isinstance(True, int) is True (!), so check for numbers lower down the chain
            return str(node.value)
        elif isinstance(node.value, str) or isinstance(node.value, list):
            self.context.values[key] = node.value
            return f"%({key})s"
        elif node.value is None:
            return "null"
        else:
            raise ValueError(
                f"Unknown AST Constant node type '{type(node.value).__name__}' for value '{str(node.value)}'"
            )

    def visit_field(self, node: ast.Field):
        original_field = ".".join([self._print_identifier(identifier) for identifier in node.chain])
        if node.symbol is None:
            raise ValueError(f"Field {original_field} has no symbol")

        if self.dialect == "hogql":
            # When printing HogQL, we print the properties out as a chain as they are.
            return ".".join([self._print_identifier(identifier) for identifier in node.chain])

        if node.symbol is not None:
            select_query = self._last_select()
            select: Optional[ast.SelectQuerySymbol] = select_query.symbol if select_query else None
            if select is None:
                raise ValueError(f"Can't find SelectQuerySymbol for field: {original_field}")
            return self.visit(node.symbol)
        else:
            raise ValueError(f"Unknown Symbol, can not print {type(node.symbol).__name__}")

    def visit_call(self, node: ast.Call):
        if node.name in HOGQL_AGGREGATIONS:
            self.context.found_aggregation = True
            required_arg_count = HOGQL_AGGREGATIONS[node.name]

            if required_arg_count != len(node.args):
                raise ValueError(
                    f"Aggregation '{node.name}' requires {required_arg_count} argument{'s' if required_arg_count != 1 else ''}, found {len(node.args)}"
                )

            # check that we're not running inside another aggregate
            for stack_node in self.stack:
                if stack_node != node and isinstance(stack_node, ast.Call) and stack_node.name in HOGQL_AGGREGATIONS:
                    raise ValueError(
                        f"Aggregation '{node.name}' cannot be nested inside another aggregation '{stack_node.name}'."
                    )

            translated_args = ", ".join([self.visit(arg) for arg in node.args])
            if self.dialect == "hogql":
                return f"{node.name}({translated_args})"
            elif node.name == "count":
                return "count(*)"
            # TODO: rework these
            elif node.name == "countDistinct":
                return f"count(distinct {translated_args})"
            elif node.name == "countDistinctIf":
                return f"countIf(distinct {translated_args})"
            else:
                return f"{node.name}({translated_args})"

        elif node.name in CLICKHOUSE_FUNCTIONS:
            return f"{CLICKHOUSE_FUNCTIONS[node.name]}({', '.join([self.visit(arg) for arg in node.args])})"
        else:
            raise ValueError(f"Unsupported function call '{node.name}(...)'")

    def visit_placeholder(self, node: ast.Placeholder):
        raise ValueError(f"Found a Placeholder {{{node.field}}} in the tree. Can't generate query!")

    def visit_alias(self, node: ast.Alias):
        inside = self.visit(node.expr)
        if isinstance(node.expr, ast.Alias):
            inside = f"({inside})"
        return f"{inside} AS {self._print_identifier(node.alias)}"

    def visit_table_symbol(self, symbol: ast.TableSymbol):
        return self._print_identifier(symbol.table.clickhouse_table())

    def visit_table_alias_symbol(self, symbol: ast.TableAliasSymbol):
        return self._print_identifier(symbol.name)

    def visit_field_symbol(self, symbol: ast.FieldSymbol):
        try:
            last_select = self._last_select()
            symbol_with_name_in_scope = lookup_field_by_name(last_select.symbol, symbol.name) if last_select else None
        except ResolverException:
            symbol_with_name_in_scope = None

        if (
            isinstance(symbol.table, ast.TableSymbol)
            or isinstance(symbol.table, ast.TableAliasSymbol)
            or isinstance(symbol.table, ast.VirtualTableSymbol)
        ):
            resolved_field = symbol.resolve_database_field()
            if resolved_field is None:
                raise ValueError(f'Can\'t resolve field "{symbol.name}" on table.')
            if isinstance(resolved_field, Table):
                if isinstance(symbol.table, ast.VirtualTableSymbol):
                    return self.visit(ast.AsteriskSymbol(table=ast.TableSymbol(table=resolved_field)))
                else:
                    return self.visit(
                        ast.AsteriskSymbol(
                            table=ast.TableAliasSymbol(
                                table_symbol=ast.TableSymbol(table=resolved_field), name=symbol.table.name
                            )
                        )
                    )

            field_sql = self._print_identifier(resolved_field.name)

            # If the field is called on a table that has an alias, prepend the table alias.
            # If there's another field with the same name in the scope that's not this, prepend the full table name.
            # Note: we don't prepend a table name for the special "person" fields.
            if isinstance(symbol.table, ast.TableAliasSymbol) or symbol_with_name_in_scope != symbol:
                field_sql = f"{self.visit(symbol.table)}.{field_sql}"

        elif isinstance(symbol.table, ast.SelectQuerySymbol) or isinstance(symbol.table, ast.SelectQueryAliasSymbol):
            field_sql = self._print_identifier(symbol.name)
            if isinstance(symbol.table, ast.SelectQueryAliasSymbol) or symbol_with_name_in_scope != symbol:
                field_sql = f"{self.visit(symbol.table)}.{field_sql}"

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.within_non_hogql_query and field_sql == "events__pdi__person.properties":
                if self.context.using_person_on_events:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"

        else:
            raise ValueError(f"Unknown FieldSymbol table type: {type(symbol.table).__name__}")

        return field_sql

    def visit_property_symbol(self, symbol: ast.PropertySymbol):
        field_symbol = symbol.parent
        field = field_symbol.resolve_database_field()

        key = f"hogql_val_{len(self.context.values)}"
        self.context.values[key] = symbol.name

        # check for a materialised column
        table = field_symbol.table
        while isinstance(table, ast.TableAliasSymbol):
            table = table.table_symbol
        if isinstance(table, ast.TableSymbol):
            table_name = table.table.clickhouse_table()
            if field is None:
                raise ValueError(f"Can't resolve field {field_symbol.name} on table {table_name}")
            field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

            materialized_column = self._get_materialized_column(table_name, symbol.name, field_name)
            if materialized_column:
                property_sql = self._print_identifier(materialized_column)
            else:
                field_sql = self.visit(field_symbol)
                property_sql = trim_quotes_expr(f"JSONExtractRaw({field_sql}, %({key})s)")
        elif (
            self.context.within_non_hogql_query
            and isinstance(table, ast.SelectQueryAliasSymbol)
            and table.name == "events__pdi__person"
        ):
            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.using_person_on_events:
                materialized_column = self._get_materialized_column("events", symbol.name, "person_properties")
            else:
                materialized_column = self._get_materialized_column("person", symbol.name, "properties")
            if materialized_column:
                property_sql = self._print_identifier(materialized_column)
            else:
                field_sql = self.visit(field_symbol)
                property_sql = trim_quotes_expr(f"JSONExtractRaw({field_sql}, %({key})s)")
        else:
            field_sql = self.visit(field_symbol)
            property_sql = trim_quotes_expr(f"JSONExtractRaw({field_sql}, %({key})s)")

        return property_sql

    def visit_select_query_alias_symbol(self, symbol: ast.SelectQueryAliasSymbol):
        return self._print_identifier(symbol.name)

    def visit_field_alias_symbol(self, symbol: ast.SelectQueryAliasSymbol):
        return self._print_identifier(symbol.name)

    def visit_virtual_table_symbol(self, symbol: ast.VirtualTableSymbol):
        return self.visit(symbol.table)

    def visit_asterisk_symbol(self, symbol: ast.AsteriskSymbol):
        raise ValueError("Unexpected ast.AsteriskSymbol. Make sure AsteriskExpander has run on the AST.")

    def visit_lazy_table_symbol(self, symbol: ast.LazyTableSymbol):
        raise ValueError("Unexpected ast.LazyTableSymbol. Make sure LazyTableResolver has run on the AST.")

    def visit_field_traverser_symbol(self, symbol: ast.FieldTraverserSymbol):
        raise ValueError("Unexpected ast.FieldTraverserSymbol. This should have been resolved.")

    def visit_unknown(self, node: ast.AST):
        raise ValueError(f"Unknown AST node {type(node).__name__}")

    def _last_select(self) -> Optional[ast.SelectQuery]:
        """Find the last SELECT query in the stack."""
        for node in reversed(self.stack):
            if isinstance(node, ast.SelectQuery):
                return node
        return None

    def _print_identifier(self, name: str) -> str:
        if self.dialect == "clickhouse":
            return print_clickhouse_identifier(name)
        return print_hogql_identifier(name)

    def _get_materialized_column(
        self, table_name: TablesWithMaterializedColumns, property_name: PropertyName, field_name: TableColumn
    ) -> Optional[str]:
        materialized_columns = get_materialized_columns(table_name)
        return materialized_columns.get((property_name, field_name), None)


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"
