from typing import List, Literal

from posthog.hogql import ast
from posthog.hogql.constants import (
    CLICKHOUSE_FUNCTIONS,
    EVENT_FIELDS,
    EVENT_PERSON_FIELDS,
    HOGQL_AGGREGATIONS,
    KEYWORDS,
    SELECT_STAR_FROM_EVENTS_FIELDS,
)
from posthog.hogql.context import HogQLContext, HogQLFieldAccess
from posthog.hogql.parser import parse_expr
from posthog.hogql.print_string import print_clickhouse_identifier


def guard_where_team_id(where: ast.Expr, context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.select_team_id:
        raise ValueError("context.select_team_id not found")

    from posthog.hogql.parser import parse_expr

    team_clause = parse_expr("team_id = {team_id}", {"team_id": ast.Constant(value=context.select_team_id)})
    if isinstance(where, ast.And):
        where = ast.And(exprs=[team_clause] + where.exprs)
    elif where:
        where = ast.And(exprs=[team_clause, where])
    else:
        where = team_clause
    return where


def print_ast(
    node: ast.AST, stack: List[ast.AST], context: HogQLContext, dialect: Literal["hogql", "clickhouse"]
) -> str:
    """Translate a parsed HogQL expression in the shape of a Python AST into a Clickhouse expression."""
    stack.append(node)

    if isinstance(node, ast.BinaryOperation):
        if node.op == ast.BinaryOperationType.Add:
            response = f"plus({print_ast(node.left, stack, context, dialect)}, {print_ast(node.right, stack, context, dialect)})"
        elif node.op == ast.BinaryOperationType.Sub:
            response = f"minus({print_ast(node.left, stack, context, dialect)}, {print_ast(node.right, stack, context, dialect)})"
        elif node.op == ast.BinaryOperationType.Mult:
            response = f"multiply({print_ast(node.left, stack, context, dialect)}, {print_ast(node.right, stack, context, dialect)})"
        elif node.op == ast.BinaryOperationType.Div:
            response = f"divide({print_ast(node.left, stack, context, dialect)}, {print_ast(node.right, stack, context, dialect)})"
        elif node.op == ast.BinaryOperationType.Mod:
            response = f"modulo({print_ast(node.left, stack, context, dialect)}, {print_ast(node.right, stack, context, dialect)})"
        else:
            raise ValueError(f"Unknown BinaryOperationType {node.op}")
    elif isinstance(node, ast.And):
        response = f"and({', '.join([print_ast(operand, stack, context, dialect) for operand in node.exprs])})"
    elif isinstance(node, ast.Or):
        response = f"or({', '.join([print_ast(operand, stack, context, dialect) for operand in node.exprs])})"
    elif isinstance(node, ast.Not):
        response = f"not({print_ast(node.expr, stack, context, dialect)})"
    elif isinstance(node, ast.OrderExpr):
        response = f"{print_ast(node.expr, stack, context, dialect)} {node.order}"
    elif isinstance(node, ast.CompareOperation):
        left = print_ast(node.left, stack, context, dialect)
        right = print_ast(node.right, stack, context, dialect)
        if node.op == ast.CompareOperationType.Eq:
            if isinstance(node.right, ast.Constant) and node.right.value is None:
                response = f"isNull({left})"
            else:
                response = f"equals({left}, {right})"
        elif node.op == ast.CompareOperationType.NotEq:
            if isinstance(node.right, ast.Constant) and node.right.value is None:
                response = f"isNotNull({left})"
            else:
                response = f"notEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Gt:
            response = f"greater({left}, {right})"
        elif node.op == ast.CompareOperationType.GtE:
            response = f"greaterOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Lt:
            response = f"less({left}, {right})"
        elif node.op == ast.CompareOperationType.LtE:
            response = f"lessOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationType.Like:
            response = f"like({left}, {right})"
        elif node.op == ast.CompareOperationType.ILike:
            response = f"ilike({left}, {right})"
        elif node.op == ast.CompareOperationType.NotLike:
            response = f"not(like({left}, {right}))"
        elif node.op == ast.CompareOperationType.NotILike:
            response = f"not(ilike({left}, {right}))"
        elif node.op == ast.CompareOperationType.In:
            response = f"in({left}, {right})"
        elif node.op == ast.CompareOperationType.NotIn:
            response = f"not(in({left}, {right}))"
        else:
            raise ValueError(f"Unknown CompareOperationType: {type(node.op).__name__}")
    elif isinstance(node, ast.Constant):
        key = f"hogql_val_{len(context.values)}"
        if isinstance(node.value, bool) and node.value is True:
            response = "true"
        elif isinstance(node.value, bool) and node.value is False:
            response = "false"
        elif isinstance(node.value, int) or isinstance(node.value, float):
            # :WATCH_OUT: isinstance(node.value, int) is True if node.value is True/False as well!!!
            response = str(node.value)
        elif isinstance(node.value, str) or isinstance(node.value, list):
            context.values[key] = node.value
            response = f"%({key})s"
        elif node.value is None:
            response = "null"
        else:
            raise ValueError(
                f"Unknown AST Constant node type '{type(node.value).__name__}' for value '{str(node.value)}'"
            )
    elif isinstance(node, ast.Field):
        if dialect == "hogql":
            response = ".".join([print_clickhouse_identifier(identifier) for identifier in node.chain])
        elif node.chain == ["*"]:
            query = f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"
            response = print_ast(parse_expr(query), stack, context, dialect)
        elif node.chain == ["person"]:
            query = "tuple(distinct_id, person.id, person.created_at, person.properties.name, person.properties.email)"
            response = print_ast(parse_expr(query), stack, context, dialect)
        else:
            field_access = parse_field_access(node.chain, context)
            context.field_access_logs.append(field_access)
            response = field_access.sql
    elif isinstance(node, ast.Call):
        if node.name in HOGQL_AGGREGATIONS:
            context.found_aggregation = True
            required_arg_count = HOGQL_AGGREGATIONS[node.name]

            if required_arg_count != len(node.args):
                raise ValueError(
                    f"Aggregation '{node.name}' requires {required_arg_count} argument{'s' if required_arg_count != 1 else ''}, found {len(node.args)}"
                )

            # check that we're not running inside another aggregate
            for stack_node in stack:
                if stack_node != node and isinstance(stack_node, ast.Call) and stack_node.name in HOGQL_AGGREGATIONS:
                    raise ValueError(
                        f"Aggregation '{node.name}' cannot be nested inside another aggregation '{stack_node.name}'."
                    )

            translated_args = ", ".join([print_ast(arg, stack, context, dialect) for arg in node.args])
            if dialect == "hogql":
                response = f"{node.name}({translated_args})"
            elif node.name == "count":
                response = "count(*)"
            elif node.name == "countDistinct":
                response = f"count(distinct {translated_args})"
            elif node.name == "countDistinctIf":
                response = f"countIf(distinct {translated_args})"
            else:
                response = f"{node.name}({translated_args})"

        elif node.name in CLICKHOUSE_FUNCTIONS:
            response = f"{CLICKHOUSE_FUNCTIONS[node.name]}({', '.join([print_ast(arg, stack, context, dialect) for arg in node.args])})"
        else:
            raise ValueError(f"Unsupported function call '{node.name}(...)'")
    elif isinstance(node, ast.Placeholder):
        raise ValueError(f"Found a Placeholder {{{node.field}}} in the tree. Can't generate query!")
    else:
        raise ValueError(f"Unknown AST node {type(node).__name__}")

    stack.pop()
    return response


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
