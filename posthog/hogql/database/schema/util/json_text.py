from posthog.hogql import ast
from posthog.hogql.visitor import clone_expr


def is_json_container_text(text: ast.Expr) -> ast.Expr:
    """Whether `text` is the JSON text of an object or an array.

    The native events table stores an object or array as a string of its JSON text, and nothing records which strings
    those are. Every reader therefore treats a string that passes this test as the object or array.
    The first character is compared by code so no brace literal reaches callers that str.format the printed SQL.
    """
    starts_with_container = ast.Call(
        name="in",
        args=[
            ast.Call(name="ascii", args=[clone_expr(text)]),
            ast.Tuple(exprs=[ast.Constant(value=ord("[")), ast.Constant(value=ord("{"))]),
        ],
    )
    return ast.Call(name="and", args=[starts_with_container, ast.Call(name="isValidJSON", args=[clone_expr(text)])])
