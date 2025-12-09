def parse_expr(expr: str, /, *, is_internal: bool = False) -> str:
    """Parse the HogQL expression string into a JSON string representation of the AST.

    If the expr `is_internal`, spans and notices won't be included in the JSON.
    The returned JSON string should be deserialized using posthog.hogql.json_ast.deserialize_ast().
    """
    ...

def parse_order_expr(expr: str, /, *, is_internal: bool = False) -> str:
    """Parse the ORDER BY clause string into a JSON string representation of the AST.

    If the expr `is_internal`, spans and notices won't be included in the JSON.
    The returned JSON string should be deserialized using posthog.hogql.json_ast.deserialize_ast().
    """
    ...

def parse_select(expr: str, /, *, is_internal: bool = False) -> str:
    """Parse the HogQL SELECT statement string into a JSON string representation of the AST.

    If the expr `is_internal`, spans and notices won't be included in the JSON.
    The returned JSON string should be deserialized using posthog.hogql.json_ast.deserialize_ast().
    """
    ...

def parse_full_template_string(expr: str, /, *, is_internal: bool = False) -> str:
    """Parse a Hog template string into a JSON string representation of the AST.

    If the expr `is_internal`, spans and notices won't be included in the JSON.
    The returned JSON string should be deserialized using posthog.hogql.json_ast.deserialize_ast().
    """
    ...

def parse_string_literal_text(value: str, /) -> str:
    """Unquote the string (an identifier or a string literal).

    Returns the unquoted string value.
    """
    ...

def parse_program(source: str, /, *, is_internal: bool = False) -> str:
    """Parse a Hog program into a JSON string representation of the AST.

    If the expr `is_internal`, spans and notices won't be included in the JSON.
    The returned JSON string should be deserialized using posthog.hogql.json_ast.deserialize_ast().
    """
    ...
