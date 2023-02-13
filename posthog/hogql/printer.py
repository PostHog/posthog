from typing import List, Literal, Optional, Union

from ee.clickhouse.materialized_columns.columns import get_materialized_columns
from posthog.hogql import ast
from posthog.hogql.constants import CLICKHOUSE_FUNCTIONS, HOGQL_AGGREGATIONS, MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext, HogQLFieldAccess
from posthog.hogql.print_string import print_hogql_identifier
from posthog.hogql.resolver import ResolverException, lookup_field_by_name
from posthog.hogql.visitor import Visitor


def guard_where_team_id(
    where: Optional[ast.Expr], table_symbol: Union[ast.TableSymbol, ast.TableAliasSymbol], context: HogQLContext
) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.select_team_id:
        raise ValueError("context.select_team_id not found")

    team_clause = ast.CompareOperation(
        op=ast.CompareOperationType.Eq,
        left=ast.Field(chain=["team_id"], symbol=ast.FieldSymbol(name="team_id", table=table_symbol)),
        right=ast.Constant(value=context.select_team_id),
    )

    if isinstance(where, ast.And):
        where = ast.And(exprs=[team_clause] + where.exprs)
    elif where:
        where = ast.And(exprs=[team_clause, where])
    else:
        where = team_clause
    return where


def print_ast(
    node: ast.AST, context: HogQLContext, dialect: Literal["hogql", "clickhouse"], stack: List[ast.AST] = []
) -> str:
    return Printer(context=context, dialect=dialect, stack=stack).visit(node)


class Printer(Visitor):
    def __init__(
        self, context: HogQLContext, dialect: Literal["hogql", "clickhouse"], stack: Optional[List[ast.AST]] = None
    ):
        self.context = context
        self.dialect = dialect
        self.stack: List[ast.AST] = stack or []

    def _last_select(self) -> Optional[ast.SelectQuery]:
        for node in reversed(self.stack):
            if isinstance(node, ast.SelectQuery):
                return node
        return None

    def visit(self, node: ast.AST):
        self.stack.append(node)
        response = super().visit(node)
        self.stack.pop()
        return response

    def visit_select_query(self, node: ast.SelectQuery):
        if self.dialect == "clickhouse" and not self.context.select_team_id:
            raise ValueError("Full SELECT queries are disabled if select_team_id is not set")

        # we will add extra clauses onto this
        where = node.where

        select_from = []
        next_join = node.select_from
        while isinstance(next_join, ast.JoinExpr):
            if next_join.symbol is None:
                raise ValueError("Printing queries with a FROM clause is not permitted before symbol resolution")

            (select_sql, extra_where) = self.visit_join_expr(next_join)
            select_from.append(select_sql)

            if extra_where is not None:
                if where is None:
                    where = extra_where
                elif isinstance(where, ast.And):
                    where = ast.And(exprs=[extra_where] + where.exprs)
                else:
                    where = ast.And(exprs=[extra_where, where])

            next_join = next_join.next_join

        columns = [self.visit(column) for column in node.select] if node.select else ["1"]
        where = self.visit(where) if where else None
        having = self.visit(node.having) if node.having else None
        prewhere = self.visit(node.prewhere) if node.prewhere else None
        group_by = [self.visit(column) for column in node.group_by] if node.group_by else None
        order_by = [self.visit(column) for column in node.order_by] if node.order_by else None

        limit = node.limit
        if self.context.limit_top_select:
            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, MAX_SELECT_RETURNED_ROWS)
                else:
                    limit = ast.Call(name="min2", args=[ast.Constant(value=MAX_SELECT_RETURNED_ROWS), limit])
            elif len(self.stack) == 1:
                limit = ast.Constant(value=MAX_SELECT_RETURNED_ROWS)

        clauses = [
            f"SELECT {'DISTINCT ' if node.distinct else ''}{', '.join(columns)}",
            f"FROM {' '.join(select_from)}" if len(select_from) > 0 else None,
            "WHERE " + where if where else None,
            f"GROUP BY {', '.join(group_by)}" if group_by and len(group_by) > 0 else None,
            "HAVING " + having if having else None,
            "PREWHERE " + prewhere if prewhere else None,
            f"ORDER BY {', '.join(order_by)}" if order_by and len(order_by) > 0 else None,
        ]
        if limit is not None:
            clauses.append(f"LIMIT {self.visit(limit)}")
            if node.offset is not None:
                clauses.append(f"OFFSET {self.visit(node.offset)}")
            if node.limit_by is not None:
                clauses.append(f"BY {', '.join([self.visit(expr) for expr in node.limit_by])}")
            if node.limit_with_ties:
                clauses.append("WITH TIES")

        response = " ".join([clause for clause in clauses if clause])
        if len(self.stack) > 1:
            response = f"({response})"
        return response

    def visit_join_expr(self, node: ast.JoinExpr) -> (str, Optional[ast.Expr]):
        # return constraints we must place on the select query
        extra_where = None

        select_from = []
        if node.join_type is not None:
            select_from.append(node.join_type)

        if isinstance(node.symbol, ast.TableAliasSymbol):
            table_symbol = node.symbol.table
            if table_symbol is None:
                raise ValueError(f"Table alias {node.symbol.name} does not resolve!")
            if not isinstance(table_symbol, ast.TableSymbol):
                raise ValueError(f"Table alias {node.symbol.name} does not resolve to a table!")
            select_from.append(print_hogql_identifier(table_symbol.table.clickhouse_table()))
            if node.alias is not None:
                select_from.append(f"AS {print_hogql_identifier(node.alias)}")

            if self.dialect == "clickhouse":
                extra_where = guard_where_team_id(None, node.symbol, self.context)

        elif isinstance(node.symbol, ast.TableSymbol):
            select_from.append(print_hogql_identifier(node.symbol.table.clickhouse_table()))

            if self.dialect == "clickhouse":
                extra_where = guard_where_team_id(None, node.symbol, self.context)

        elif isinstance(node.symbol, ast.SelectQuerySymbol):
            select_from.append(self.visit(node.table))

        elif isinstance(node.symbol, ast.SelectQueryAliasSymbol) and node.alias is not None:
            select_from.append(self.visit(node.table))
            select_from.append(f"AS {print_hogql_identifier(node.alias)}")
        else:
            raise ValueError("Only selecting from a table or a subquery is supported")

        if node.table_final:
            select_from.append("FINAL")

        if node.constraint is not None:
            select_from.append(f"ON {self.visit(node.constraint)}")

        return (" ".join(select_from), extra_where)

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
        original_field = ".".join([print_hogql_identifier(identifier) for identifier in node.chain])
        if node.symbol is None:
            raise ValueError(f"Field {original_field} has no symbol")

        if self.dialect == "hogql":
            # When printing HogQL, we print the properties out as a chain instead of converting them to Clickhouse SQL
            return ".".join([print_hogql_identifier(identifier) for identifier in node.chain])
        # elif node.chain == ["*"]:
        #     query = f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"
        #     return self.visit(parse_expr(query))
        # elif node.chain == ["person"]:
        #     query = "tuple(distinct_id, person.id, person.created_at, person.properties.name, person.properties.email)"
        #     return self.visit(parse_expr(query))
        elif node.symbol is not None:
            select_query = self._last_select()
            select: Optional[ast.SelectQuerySymbol] = select_query.symbol if select_query else None
            if select is None:
                raise ValueError(f"Can't find SelectQuerySymbol for field: {original_field}")
            return SymbolPrinter(select=select, context=self.context).visit(node.symbol)
        else:
            raise ValueError(f"Unknown Symbol, can not print {type(node.symbol)}")

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
        return f"{self.visit(node.expr)} AS {print_hogql_identifier(node.alias)}"

    def visit_unknown(self, node: ast.AST):
        raise ValueError(f"Unknown AST node {type(node).__name__}")


class SymbolPrinter(Visitor):
    def __init__(self, select: ast.SelectQuerySymbol, context: HogQLContext):
        self.select = select
        self.context = context

    def visit_table_symbol(self, symbol: ast.TableSymbol):
        return print_hogql_identifier(symbol.table.clickhouse_table())

    def visit_table_alias_symbol(self, symbol: ast.TableAliasSymbol):
        return print_hogql_identifier(symbol.name)

    def visit_field_symbol(self, symbol: ast.FieldSymbol):
        printed_field = print_hogql_identifier(symbol.name)

        try:
            symbol_with_name_in_scope = lookup_field_by_name(self.select, symbol.name)
        except ResolverException:
            symbol_with_name_in_scope = None

        if (
            symbol_with_name_in_scope != symbol
            or isinstance(symbol.table, ast.TableAliasSymbol)
            or isinstance(symbol.table, ast.SelectQueryAliasSymbol)
        ):
            table_prefix = self.visit(symbol.table)
            field_sql = f"{table_prefix}.{printed_field}"
        else:
            field_sql = printed_field

        if printed_field != "properties":
            # TODO: refactor this property access logging
            self.context.field_access_logs.append(
                HogQLFieldAccess(
                    [symbol.name],
                    "event",
                    symbol.name,
                    field_sql,
                )
            )

        return field_sql

    def visit_property_symbol(self, symbol: ast.PropertySymbol):
        key = f"hogql_val_{len(self.context.values)}"
        self.context.values[key] = symbol.name

        table = symbol.field.table
        if isinstance(table, ast.TableAliasSymbol):
            table = table.table

        # TODO: cache this
        materialized_columns = get_materialized_columns(table.table.clickhouse_table())
        materialized_column = materialized_columns.get((symbol.name, "properties"), None)

        if materialized_column:
            property_sql = print_hogql_identifier(materialized_column)
        else:
            field_sql = self.visit(symbol.field)
            property_sql = trim_quotes_expr(f"JSONExtractRaw({field_sql}, %({key})s)")

        self.context.field_access_logs.append(
            HogQLFieldAccess(
                ["properties", symbol.name],
                "event.properties",
                symbol.name,
                property_sql,
            )
        )

        return property_sql

    def visit_select_query_alias_symbol(self, symbol: ast.SelectQueryAliasSymbol):
        return print_hogql_identifier(symbol.name)

    def visit_column_alias_symbol(self, symbol: ast.SelectQueryAliasSymbol):
        return print_hogql_identifier(symbol.name)

    def visit_unknown(self, symbol: ast.AST):
        raise ValueError(f"Unknown Symbol {type(symbol).__name__}")


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"
