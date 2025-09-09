from posthog.hogql.ast import Program, SelectQuery, SelectSetQuery
from posthog.hogql.base import AST

def parse_expr(expr: str, /, *, is_internal: bool = False) -> AST:
    """Parse the HogQL expression string into an AST.

    If the expr `is_internal`, spans and notices won't be included in the AST.
    """
    ...

def parse_order_expr(expr: str, /, *, is_internal: bool = False) -> AST:
    """Parse the ORDER BY clause string into an AST.

    If the expr `is_internal`, spans and notices won't be included in the AST.
    """
    ...

def parse_select(expr: str, /, *, is_internal: bool = False) -> SelectQuery | SelectSetQuery:
    """Parse the HogQL SELECT statement string into an AST.

    If the expr `is_internal`, spans and notices won't be included in the AST.
    """
    ...

def parse_full_template_string(expr: str, /, *, is_internal: bool = False) -> AST:
    """Parse a Hog template string into an AST.

    If the expr `is_internal`, spans and notices won't be included in the AST.
    """
    ...

def parse_string_literal_text(value: str, /) -> str:
    """Unquote the string (an identifier or a string literal).

    If the expr is `internal`, spans and notices won't be included in the AST.
    """
    ...

def parse_program(source: str, /, *, is_internal: bool = False) -> Program:
    """Parse a Hog program.

    If the expr `is_internal`, spans and notices won't be included in the AST.
    """
    ...
