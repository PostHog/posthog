from posthog.hogql.ast import SelectQuery, SelectUnionQuery
from posthog.hogql.base import AST

def parse_expr(expr: str, /) -> AST:
    """Parse the HogQL expression string into an AST"""
    ...

def parse_order_expr(expr: str, /) -> AST:
    """Parse the ORDER BY clause string into an AST"""
    ...

def parse_select(expr: str, /) -> SelectQuery | SelectUnionQuery:
    """Parse the HogQL SELECT statement string into an AST"""
    ...

def unquote_string(value: str, /) -> str:
    """Unquote the string (an identifier or a string literal)"""
    ...
