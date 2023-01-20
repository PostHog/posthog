# mypy: allow-untyped-defs
import ast
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

from clickhouse_driver.util.escape import escape_param

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
class HogQLContext:
    """Context given to a HogQL expression parser"""

    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: Optional[Dict] = field(default_factory=dict)
    # List of field and property accesses found in the expression
    attribute_list: List[List[str]] = field(default_factory=list)
    # Did the last calls to translate_hogql since setting this to False contain any HOGQL_AGGREGATIONS
    found_aggregation: bool = False


def translate_hogql(hql: str, context: HogQLContext) -> str:
    """Translate a HogQL expression into a Clickhouse expression."""
    if hql == "*":
        return f"tuple({','.join(SELECT_STAR_FROM_EVENTS_FIELDS)})"

    # The expression "person" can't be used in a query, just top level
    if hql == "person":
        hql = "tuple(distinct_id, person.id, person.created_at, person.properties.name, person.properties.email)"

    try:
        # Until we swap out the AST parser, we're limited to Python's dialect.
        # This means "properties.$bla" fails. The following is a hack to get around that for now.
        hql = re.sub(r"properties\.(\$[$a-zA-Z0-9_\-]+)", r"properties['\1']", hql)
        node = ast.parse(hql)
    except SyntaxError as err:
        raise ValueError(f"SyntaxError: {err.msg}")
    return translate_ast(node, [], context)


def translate_ast(node: ast.AST, stack: List[ast.AST], context: HogQLContext) -> str:
    """Translate a parsed HogQL expression in the shape of a Python AST into a Clickhouse expression."""
    stack.append(node)
    if isinstance(node, ast.Module):
        if len(node.body) == 1 and isinstance(node.body[0], ast.Expr):
            response = translate_ast(node.body[0], stack, context)
        else:
            raise ValueError(f"Module body must contain only one 'Expr'")
    elif isinstance(node, ast.Expr):
        ast.dump(node)
        response = translate_ast(node.value, stack, context)
    elif isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            response = f"plus({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
        elif isinstance(node.op, ast.Sub):
            response = f"minus({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
        elif isinstance(node.op, ast.Mult):
            response = (
                f"multiply({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        elif isinstance(node.op, ast.Div):
            response = (
                f"divide({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        elif isinstance(node.op, ast.Mod):
            response = (
                f"modulo({translate_ast(node.left, stack, context)}, {translate_ast(node.right, stack, context)})"
            )
        else:
            response = f"({translate_ast(node.left, stack, context)} {translate_ast(node.op, stack, context)} {translate_ast(node.right, stack, context)})"
    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            response = f"and({', '.join([translate_ast(operand, stack, context) for operand in node.values])})"
        elif isinstance(node.op, ast.Or):
            response = f"or({', '.join([translate_ast(operand, stack, context) for operand in node.values])})"
        else:
            raise ValueError(f"Unknown BoolOp: {type(node.op)}")
    elif isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            response = f"not({translate_ast(node.operand, stack, context)})"
        elif isinstance(node.op, ast.USub):
            response = f"-{translate_ast(node.operand, stack, context)}"
        else:
            raise ValueError(f"Unknown UnaryOp: {type(node.op)}")
    elif isinstance(node, ast.Compare):
        if isinstance(node.ops[0], ast.Eq):
            response = f"equals({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        elif isinstance(node.ops[0], ast.NotEq):
            response = f"notEquals({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        elif isinstance(node.ops[0], ast.Gt):
            response = f"greater({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        elif isinstance(node.ops[0], ast.GtE):
            response = f"greaterOrEquals({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        elif isinstance(node.ops[0], ast.Lt):
            response = f"less({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        elif isinstance(node.ops[0], ast.LtE):
            response = f"lessOrEquals({translate_ast(node.left, stack, context)}, {translate_ast(node.comparators[0], stack, context)})"
        else:
            raise ValueError(f"Unknown Compare: {type(node.ops[0])}")
    elif isinstance(node, ast.Constant):
        key = f"val_{len(context.values or {})}"
        if isinstance(node.value, int) or isinstance(node.value, float):
            response = str(node.value)
        elif isinstance(node.value, str):
            if isinstance(context.values, dict):
                context.values[key] = node.value
                response = f"%({key})s"
            else:
                response = escape_param(node.value)
        else:
            raise ValueError(f"Unknown AST Constant node type '{type(node.value)}' for value '{str(node.value)}'")
    elif isinstance(node, ast.Attribute) or isinstance(node, ast.Subscript):
        attribute_chain: List[str] = []
        while True:
            if isinstance(node, ast.Attribute):
                attribute_chain.insert(0, node.attr)
                node = node.value
            elif isinstance(node, ast.Subscript):
                node_slice: ast.AST = node.slice
                if isinstance(node_slice, ast.Constant):
                    if not isinstance(node_slice.value, str):
                        raise ValueError(
                            f"Only string property access is currently supported, found '{node_slice.value}'"
                        )
                    attribute_chain.insert(0, node_slice.value)
                    node = node.value
                # ast.Index is a deprecated node class that shows up in tests with Python 3.8
                # Must do some manual casting, or mypy will give different unresolvable errors between 3.8 and 3.9
                elif isinstance(node_slice, ast.Index) and isinstance(cast(Any, node_slice).value, ast.Constant):
                    const = cast(ast.Constant, cast(Any, node_slice).value)
                    if not isinstance(const.value, str):
                        raise ValueError(f"Only string property access is currently supported, found '{const.value}'")
                    attribute_chain.insert(0, const.value)
                    node = node.value
                else:
                    raise ValueError(f"Unsupported Subscript slice type: {type(node.slice).__name__}")
            elif isinstance(node, ast.Name):  # type: ignore
                attribute_chain.insert(0, node.id)
                break
            elif isinstance(node, ast.Constant):
                attribute_chain.insert(0, node.value)
                break
            else:
                raise ValueError(f"Unknown node in field access chain: {ast.dump(node)}")
        response = property_access_to_clickhouse(attribute_chain)
        context.attribute_list.append(attribute_chain)

    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError(f"Can only call simple functions like 'avg(properties.bla)' or 'count()'")
        call_name = node.func.id
        if call_name in HOGQL_AGGREGATIONS:
            context.found_aggregation = True
            required_arg_count = HOGQL_AGGREGATIONS[call_name]

            if required_arg_count != len(node.args):
                raise ValueError(
                    f"Aggregation '{call_name}' requires {required_arg_count} argument{'s' if required_arg_count != 1 else ''}, found {len(node.args)}"
                )

            # check that we're not running inside another aggregate
            for stack_node in stack:
                if (
                    stack_node != node
                    and isinstance(stack_node, ast.Call)
                    and isinstance(stack_node.func, ast.Name)
                    and stack_node.func.id in HOGQL_AGGREGATIONS
                ):
                    raise ValueError(
                        f"Aggregation '{call_name}' cannot be nested inside another aggregation '{stack_node.func.id}'."
                    )

            translated_args = ", ".join([translate_ast(arg, stack, context) for arg in node.args])
            if call_name == "count":
                response = "count(*)"
            elif call_name == "countDistinct":
                response = f"count(distinct {translated_args})"
            elif call_name == "countDistinctIf":
                response = f"countIf(distinct {translated_args})"
            else:
                response = f"{call_name}({translated_args})"

        elif node.func.id in CLICKHOUSE_FUNCTIONS:
            response = f"{CLICKHOUSE_FUNCTIONS[node.func.id]}({', '.join([translate_ast(arg, stack, context) for arg in node.args])})"
        else:
            raise ValueError(f"Unsupported function call '{call_name}(...)'")
    elif isinstance(node, ast.Name) and isinstance(node.id, str):
        response = property_access_to_clickhouse([node.id])
        context.attribute_list.append([node.id])
    else:
        ast.dump(node)
        raise ValueError(f"Unknown AST type {type(node).__name__}")

    stack.pop()
    return response


def property_access_to_clickhouse(chain: List[str]):
    # Circular import otherwise
    from posthog.models.property.util import get_property_string_expr

    """Given a list like ['properties', '$browser'] or ['uuid'], translate to the correct ClickHouse expr."""
    if len(chain) == 2:
        if chain[0] == "properties":
            expression, _ = get_property_string_expr(
                "events",
                chain[1],
                escape_param(chain[1]),
                "properties",
            )
            return expression
        elif chain[0] == "person":
            if chain[1] in EVENT_PERSON_FIELDS:
                return f"person_{chain[1]}"
            else:
                raise ValueError(f"Unknown person field '{chain[1]}'")
    elif len(chain) == 3 and chain[0] == "person" and chain[1] == "properties":
        expression, _ = get_property_string_expr(
            "events",
            chain[2],
            escape_param(chain[2]),
            "person_properties",
            materialised_table_column="person_properties",
        )
        return expression
    elif len(chain) == 1:
        if chain[0] in EVENT_FIELDS:
            if chain[0] == "id":
                return "uuid"
            return chain[0]
        elif chain[0].startswith("person_") and chain[0][7:] in EVENT_PERSON_FIELDS:
            return chain[0]
        elif chain[0].lower() in KEYWORDS:
            return chain[0].lower()
        elif chain[0] == "person":
            raise ValueError(f'Can not use the field "person" in an expression')
        else:
            raise ValueError(f"Unknown event field '{chain[0]}'")

    raise ValueError(f"Unsupported property access: {chain}")
