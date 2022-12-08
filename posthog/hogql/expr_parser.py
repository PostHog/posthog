import ast
from typing import List

from clickhouse_driver.util.escape import escape_param

from posthog.models.property.util import get_property_string_expr

EVENT_FIELDS = ["id", "uuid", "event", "timestamp", "distinct_id"]
PERSON_FIELDS = ["id", "created_at", "properties"]
CLICKHOUSE_FUNCTIONS = ["concat", "coalesce"]


def translate_hql(hql: str) -> str:
    """Translate a HogQL expression into a Clickhouse expression."""
    try:
        node = ast.parse(hql)
    except SyntaxError as err:
        raise ValueError(f"SyntaxError: {err.msg}")
    return translate_ast(node)


def translate_ast(node: ast.AST) -> str:
    """Translate a parsed HogQL expression in the shape of a Python AST into a Clickhouse expression."""
    if type(node) == ast.Module:
        if len(node.body) == 1 and type(node.body[0]) == ast.Expr:
            return translate_ast(node.body[0])
        raise ValueError(f"Module body must contain only one 'Expr'")
    elif type(node) == ast.Expr:
        return translate_ast(node.value)
    elif type(node) == ast.BinOp:
        if type(node.op) == ast.Add:
            return f"plus({translate_ast(node.left)}, {translate_ast(node.right)})"
        if type(node.op) == ast.Sub:
            return f"minus({translate_ast(node.left)}, {translate_ast(node.right)})"
        if type(node.op) == ast.Mult:
            return f"multiply({translate_ast(node.left)}, {translate_ast(node.right)})"
        if type(node.op) == ast.Div:
            return f"divide({translate_ast(node.left)}, {translate_ast(node.right)})"
        return f"({translate_ast(node.left)} {translate_ast(node.op)} {translate_ast(node.right)})"
    elif type(node) == ast.UnaryOp:
        return f"{translate_ast(node.op)}{translate_ast(node.operand)}"
    elif type(node) == ast.USub:
        return "-"
    elif type(node) == ast.Constant:
        if type(node.value) == int or type(node.value) == float:
            return str(node.value)
        elif type(node.value) == str or type(node.value) == list:
            return escape_param(node.value)
        else:
            raise ValueError(f"Unknown AST Constant node type '{type(node.value)}' for value '{str(node.value)}'")
    elif type(node) == ast.Attribute or type(node) == ast.Subscript:
        attribute_chain: list[str] = []
        while True:
            if type(node) == ast.Attribute:
                attribute_chain.insert(0, node.attr)
                node = node.value
            elif type(node) == ast.Subscript:
                if type(node.slice) == ast.Constant:
                    if type(node.slice.value) != str:
                        raise ValueError(
                            f"Only string property access is currently supported, found '{node.slice.value}'"
                        )
                    attribute_chain.insert(0, node.slice.value)
                    node = node.value
                else:
                    raise ValueError(f"Unsupported Subscript slice type: {type(node.slice).__name__}")
            elif type(node) == ast.Name:  # type: ignore
                attribute_chain.insert(0, node.id)
                break
            else:
                raise ValueError(f"Unknown node in field access chain: {ast.dump(node)}")
        return property_access_to_clickhouse(attribute_chain)
    elif type(node) == ast.Call:
        if type(node.func) != ast.Name:
            raise ValueError(f"Can only call simple functions like 'avg(properties.bla)' or 'total()'")

        call_name = node.func.id
        if call_name == "total":
            if len(node.args) != 0:
                raise ValueError(f"Method 'total' does not accept any arguments.")
            return "count(*)"
        elif call_name == "avg":
            if len(node.args) != 1:
                raise ValueError(f"Method 'avg' expects just one argument.")
            return f"avg({translate_ast(node.args[0])})"
        if node.func.id in CLICKHOUSE_FUNCTIONS:
            return f"{node.func.id}({', '.join([translate_ast(arg) for arg in node.args])})"
        else:
            raise ValueError(f"Unsupported function call '{call_name}(...)'")
    elif type(node) == ast.Name and type(node.id) == str:
        return property_access_to_clickhouse([node.id])
    else:
        ast.dump(node)
        raise ValueError(f"Unknown AST type {type(node).__name__}")


def property_access_to_clickhouse(chain: List[str]):
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
            if chain[1] in PERSON_FIELDS:
                return f"person_{chain[1]}"
            else:
                raise ValueError(f"Unknown person field '{chain[1]}'")
    elif len(chain) == 3 and chain[0] == "person" and chain[1] == "properties":
        expression, _ = get_property_string_expr(
            "events",
            chain[2],
            escape_param(chain[2]),
            "person_properties",
        )
        return expression
    elif len(chain) == 1:
        if chain[0] in EVENT_FIELDS:
            if chain[0] == "id":
                return "uuid"
            return chain[0]
        elif chain[0].startswith("person_") and chain[0][7:] in PERSON_FIELDS:
            return chain[0]
        else:
            raise ValueError(f"Unknown event field '{chain[0]}'")

    raise ValueError(f"Unsupported property access: {chain}")
