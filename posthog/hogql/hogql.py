# mypy: allow-untyped-defs
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

# fields you can select from in the events query
EVENT_FIELDS = ["id", "uuid", "event", "timestamp", "distinct_id"]
# "person.*" fields you can select from in the events query
EVENT_PERSON_FIELDS = ["id", "created_at", "properties"]

# HogQL -> ClickHouse allowed transformations
CLICKHOUSE_FUNCTIONS = {
    # arithmetic
    "abs": "abs",
    "max2": "max2",
    "min2": "min2",
    # type conversions
    "toInt": "toInt64OrNull",
    "toFloat": "toFloat64OrNull",
    "toDecimal": "toDecimal64OrNull",
    "toDate": "toDateOrNull",
    "toDateTime": "parseDateTimeBestEffort",
    "toIntervalSecond": "toIntervalSecond",
    "toIntervalMinute": "toIntervalMinute",
    "toIntervalHour": "toIntervalHour",
    "toIntervalDay": "toIntervalDay",
    "toIntervalWeek": "toIntervalWeek",
    "toIntervalMonth": "toIntervalMonth",
    "toIntervalQuarter": "toIntervalQuarter",
    "toIntervalYear": "toIntervalYear",
    "toString": "toString",
    # date functions
    "now": "now",
    "toMonday": "toMonday",
    "toStartOfYear": "toStartOfYear",
    "toStartOfQuarter": "toStartOfQuarter",
    "toStartOfMonth": "toStartOfMonth",
    "toStartOfWeek": "toStartOfWeek",
    "toStartOfDay": "toStartOfDay",
    "toStartOfHour": "toStartOfHour",
    "toStartOfMinute": "toStartOfMinute",
    "toStartOfSecond": "toStartOfSecond",
    "toStartOfFiveMinutes": "toStartOfFiveMinutes",
    "toStartOfTenMinutes": "toStartOfTenMinutes",
    "toStartOfFifteenMinutes": "toStartOfFifteenMinutes",
    "toTimezone": "toTimezone",
    "age": "age",
    "dateDiff": "dateDiff",
    "dateTrunc": "dateTrunc",
    "formatDateTime": "formatDateTime",
    # string functions
    "length": "lengthUTF8",
    "empty": "empty",
    "notEmpty": "notEmpty",
    "leftPad": "leftPad",
    "rightPad": "rightPad",
    "lower": "lower",
    "upper": "upper",
    "repeat": "repeat",
    "format": "format",
    "concat": "concat",
    "coalesce": "coalesce",
    "substring": "substringUTF8",
    "appendTrailingCharIfAbsent": "appendTrailingCharIfAbsent",
    "endsWith": "endsWith",
    "startsWith": "startsWith",
    "trim": "trimBoth",
    "trimLeft": "trimLeft",
    "trimRight": "trimRight",
    "extractTextFromHTML": "extractTextFromHTML",
    "like": "like",
    "ilike": "ilike",
    "notLike": "notLike",
    "replace": "replace",
    "replaceOne": "replaceOne",
    # array functions
    "tuple": "tuple",
    # conditional
    "ifElse": "if",
    "multiIf": "multiIf",
    # rounding
    "round": "round",
    "floor": "floor",
    "ceil": "ceil",
    "trunc": "trunc",
}
# Permitted HogQL aggregations
HOGQL_AGGREGATIONS = {
    "count": 0,
    "countIf": 1,
    "countDistinct": 1,
    "countDistinctIf": 2,
    "min": 1,
    "minIf": 2,
    "max": 1,
    "maxIf": 2,
    "sum": 1,
    "sumIf": 2,
    "avg": 1,
    "avgIf": 2,
    "any": 1,
    "anyIf": 2,
}
# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Allow-listed fields returned when you select "*" from events. Person and group fields will be nested later.
SELECT_STAR_FROM_EVENTS_FIELDS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_id",
    "person_created_at",
    "person_properties",
]


@dataclass
class HogQLFieldAccess:
    input: List[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class HogQLContext:
    """Context given to a HogQL expression parser"""

    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: Dict = field(default_factory=dict)
    # List of field and property accesses found in the expression
    field_access_logs: List[HogQLFieldAccess] = field(default_factory=list)
    # Did the last calls to translate_hogql since setting these to False contain any of the following
    found_aggregation: bool = False
    using_person_on_events: bool = True


def translate_hogql(query: str, context: HogQLContext) -> str:
    """Translate a HogQL expression into a Clickhouse expression."""
    if query == "":
        raise ValueError("Empty query")
    if query == "*":
        return f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"

    # The expression "person" can't be used in a query, just top level
    if query == "person":
        query = "tuple(distinct_id, person.id, person.created_at, person.properties.name, person.properties.email)"

    try:
        node = parse_expr(query)
    except SyntaxError as err:
        raise ValueError(f"SyntaxError: {err.msg}")
    except NotImplementedError as err:
        raise ValueError(f"NotImplementedError: {err}")
    return translate_ast(node, [], context)


def translate_ast(node: ast.AST, stack: List[ast.AST], context: HogQLContext) -> str:
    """Translate a parsed HogQL expression in the shape of a Python AST into a Clickhouse expression."""
    stack.append(node)
    if isinstance(node, ast.BinaryOperation):
        if node.op == ast.BinaryOperationType.Add:
            response = f"plus({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
        elif node.op == ast.BinaryOperationType.Sub:
            response = f"minus({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
        elif node.op == ast.BinaryOperationType.Mult:
            response = (
                f"multiply({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        elif node.op == ast.BinaryOperationType.Div:
            response = (
                f"divide({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        elif node.op == ast.BinaryOperationType.Mod:
            response = (
                f"modulo({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        else:
            raise ValueError(f"Unknown BinaryOperationType {node.op}")
    elif isinstance(node, ast.BooleanOperation):
        if node.op == ast.BooleanOperationType.And:
            response = f"and({', '.join([translate_ast(operand, stack, context) for operand in node.values])})"
        elif node.op == ast.BooleanOperationType.Or:
            response = f"or({', '.join([translate_ast(operand, stack, context) for operand in node.values])})"
        else:
            raise ValueError(f"Unknown BooleanOperationType: {type(node.op)}")
    elif isinstance(node, ast.NotOperation):
        response = f"not({translate_ast(node.expr, stack, context)})"
    elif isinstance(node, ast.CompareOperation):
        left = translate_ast(node.left, stack, context)
        right = translate_ast(node.right, stack, context)
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
        else:
            raise ValueError(f"Unknown CompareOperationType: {type(node.op)}")
    elif isinstance(node, ast.Constant):
        key = f"hogql_val_{len(context.values)}"
        if isinstance(node.value, bool) and node.value is True:
            response = "true"
        elif isinstance(node.value, bool) and node.value is False:
            response = "false"
        elif isinstance(node.value, int) or isinstance(node.value, float):
            # :WATCH_OUT: isinstance(node.value, int) is True if node.value is True/False as well!!!
            response = str(node.value)
        elif isinstance(node.value, str):
            context.values[key] = node.value
            response = f"%({key})s"
        elif node.value is None:
            response = "null"
        else:
            raise ValueError(f"Unknown AST Constant node type '{type(node.value)}' for value '{str(node.value)}'")
    elif isinstance(node, ast.FieldAccess):
        field_access = parse_field_access([node.field], context)
        context.field_access_logs.append(field_access)
        response = field_access.sql
    elif isinstance(node, ast.FieldAccessChain):
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

            translated_args = ", ".join([translate_ast(arg, stack, context) for arg in node.args])
            if node.name == "count":
                response = "count(*)"
            elif node.name == "countDistinct":
                response = f"count(distinct {translated_args})"
            elif node.name == "countDistinctIf":
                response = f"countIf(distinct {translated_args})"
            else:
                response = f"{node.name}({translated_args})"

        elif node.name in CLICKHOUSE_FUNCTIONS:
            response = f"{CLICKHOUSE_FUNCTIONS[node.name]}({', '.join([translate_ast(arg, stack, context) for arg in node.args])})"
        else:
            raise ValueError(f"Unsupported function call '{node.name}(...)'")
    elif isinstance(node, ast.Parens):
        response = f"({translate_ast(node.expr, stack, context)})"
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
            return HogQLFieldAccess(chain, "event", chain[0], chain[0])
        elif chain[0].startswith("person_") and chain[0][7:] in EVENT_PERSON_FIELDS:
            return HogQLFieldAccess(chain, "person", chain[0][7:], chain[0])
        elif chain[0].lower() in KEYWORDS:
            return HogQLFieldAccess(chain, None, None, chain[0].lower())
        elif chain[0] == "person":
            raise ValueError(f'Can not use the field "person" in an expression')
        else:
            raise ValueError(f"Unknown event field '{chain[0]}'")

    raise ValueError(f"Unsupported property access: {chain}")
