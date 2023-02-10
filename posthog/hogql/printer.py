from typing import List, Literal

from posthog.hogql import ast
from posthog.hogql.constants import (
    CLICKHOUSE_FUNCTIONS,
    EVENT_FIELDS,
    EVENT_PERSON_FIELDS,
    HOGQL_AGGREGATIONS,
    KEYWORDS,
    MAX_SELECT_RETURNED_ROWS,
    SELECT_STAR_FROM_EVENTS_FIELDS,
)
from posthog.hogql.context import HogQLContext, HogQLFieldAccess
from posthog.hogql.parser import parse_expr
from posthog.hogql.print_string import print_hogql_identifier
from posthog.hogql.visitor import Visitor


def guard_where_team_id(where: ast.Expr, context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.select_team_id:
        raise ValueError("context.select_team_id not found")

    team_clause = parse_expr("team_id = {team_id}", {"team_id": ast.Constant(value=context.select_team_id)})
    if isinstance(where, ast.And):
        where = ast.And(exprs=[team_clause] + where.exprs)
    elif where:
        where = ast.And(exprs=[team_clause, where])
    else:
        where = team_clause
    return where


def print_ast(node: ast.AST, context: HogQLContext, dialect: Literal["hogql", "clickhouse"]) -> str:
    return Printer(context=context, dialect=dialect).visit(node)


class Printer(Visitor):
    def __init__(self, context: HogQLContext, dialect: Literal["hogql", "clickhouse"]):
        self.context = context
        self.dialect = dialect
        self.stack: List[ast.AST] = []

    def visit(self, node: ast.AST):
        self.stack.append(node)
        response = super().visit(node)
        self.stack.pop()
        return response

    def visit_select_query(self, node: ast.SelectQuery):
        if self.dialect == "clickhouse" and not self.context.select_team_id:
            raise ValueError("Full SELECT queries are disabled if select_team_id is not set")

        columns = [self.visit(column) for column in node.select] if node.select else ["1"]

        from_table = None
        if node.select_from:
            if node.symbol:
                if isinstance(node.symbol, ast.TableSymbol):
                    if node.symbol.table_name != "events":
                        raise ValueError('Only selecting from the "events" table is supported')
                    from_table = f"events"
                    if node.symbol.print_name:
                        from_table = f"{from_table} AS {node.symbol.print_name}"
                elif isinstance(node.symbol, ast.SelectQuerySymbol):
                    from_table = f"({self.visit(node.select_from.table)})"
                    if node.symbol.print_name:
                        from_table = f"{from_table} AS {node.symbol.print_name}"
            else:
                if node.select_from.alias is not None:
                    raise ValueError("Table aliases not yet supported")
                if isinstance(node.select_from.table, ast.Field):
                    if node.select_from.table.chain != ["events"]:
                        raise ValueError('Only selecting from the "events" table is supported')
                    from_table = "events"
                elif isinstance(node.select_from.table, ast.SelectQuery):
                    from_table = f"({self.visit(node.select_from.table)})"
                else:
                    raise ValueError("Only selecting from a table or a subquery is supported")

        where = node.where
        # Guard with team_id if selecting from a table and printing ClickHouse SQL
        # We do this in the printer, and not in a separate step, to be really sure this gets added.
        # This will be improved when we add proper table and column alias support. For now, let's just be safe.
        if self.dialect == "clickhouse" and from_table is not None:
            where = guard_where_team_id(where, self.context)
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
            f"FROM {from_table}" if from_table else None,
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
        if self.dialect == "hogql":
            # When printing HogQL, we print the properties out as a chain instead of converting them to Clickhouse SQL
            return ".".join([print_hogql_identifier(identifier) for identifier in node.chain])
        elif node.chain == ["*"]:
            query = f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"
            return self.visit(parse_expr(query))
        elif node.chain == ["person"]:
            query = "tuple(distinct_id, person.id, person.created_at, person.properties.name, person.properties.email)"
            return self.visit(parse_expr(query))
        elif node.symbol is not None:
            if isinstance(node.symbol, ast.FieldSymbol):
                return f"{node.symbol.table.print_name}.{node.symbol.name}"
            elif isinstance(node.symbol, ast.TableSymbol):
                return node.symbol.print_name
            else:
                raise ValueError(f"Unknown Symbol, can not print {type(node.symbol)}")
        else:
            field_access = parse_field_access(node.chain, self.context)
            self.context.field_access_logs.append(field_access)
            return field_access.sql

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

    def visit_unknown(self, node: ast.AST):
        raise ValueError(f"Unknown AST node {type(node).__name__}")


def parse_field_access(chain: List[str], context: HogQLContext) -> HogQLFieldAccess:
    # Circular import otherwise
    from posthog.models.property.util import get_property_string_expr

    """Given a list like ['properties', '$browser'] or ['uuid'], translate to the correct ClickHouse expr."""
    if len(chain) == 2:
        if chain[0] == "properties":
            key = f"hogql_val_{len(context.values)}"
            context.values[key] = chain[1]
            escaped_key = f"%({key})s"
            expression, _ = get_property_string_expr(
                "events",
                chain[1],
                escaped_key,
                "properties",
            )
            return HogQLFieldAccess(chain, "event.properties", chain[1], expression)
        elif chain[0] == "person":
            if chain[1] in EVENT_PERSON_FIELDS:
                return HogQLFieldAccess(chain, "person", chain[1], f"person_{chain[1]}")
            else:
                raise ValueError(f"Unknown person field '{chain[1]}'")
    elif len(chain) == 3 and chain[0] == "person" and chain[1] == "properties":
        key = f"hogql_val_{len(context.values or {})}"
        context.values[key] = chain[2]
        escaped_key = f"%({key})s"

        if context.using_person_on_events:
            expression, _ = get_property_string_expr(
                "events",
                chain[2],
                escaped_key,
                "person_properties",
                materialised_table_column="person_properties",
            )

        else:
            expression, _ = get_property_string_expr(
                "person",
                chain[2],
                escaped_key,
                "person_props",
                materialised_table_column="properties",
            )

        return HogQLFieldAccess(chain, "person.properties", chain[2], expression)
    elif len(chain) == 1:
        if chain[0] in EVENT_FIELDS:
            if chain[0] == "id":
                return HogQLFieldAccess(chain, "event", "uuid", "uuid")
            elif chain[0] == "properties":
                return HogQLFieldAccess(chain, "event", "properties", "properties")
            return HogQLFieldAccess(chain, "event", chain[0], chain[0])
        elif chain[0].startswith("person_") and chain[0][7:] in EVENT_PERSON_FIELDS:
            return HogQLFieldAccess(chain, "person", chain[0][7:], chain[0])
        elif chain[0].lower() in KEYWORDS:
            return HogQLFieldAccess(chain, None, None, chain[0].lower())
        else:
            raise ValueError(f"Unknown event field '{chain[0]}'")

    raise ValueError(f"Unsupported property access: {chain}")
