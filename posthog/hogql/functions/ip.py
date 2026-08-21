"""Crash-safe address handling for HogQL's isIPAddressInRange."""

from posthog.hogql import ast
from posthog.hogql.visitor import clone_expr


def safe_ip_address_arg(address: ast.Expr) -> ast.Expr:
    """Pass a valid IP value through unchanged; replace anything else with '::'.

    The value keeps its original text when it parses as IPv4 or IPv6, so IPv4 addresses still
    match IPv4 CIDR ranges (ClickHouse does not map IPv4 into IPv6 for isIPAddressInRange).
    A NULL or unparsable value becomes '::', a valid address that matches no real range.

    toString normalizes the argument first, so a native IPv4 or IPv6 column works as well as a
    string one - isIPv4String and isIPv6String only accept String.
    """
    normalized: ast.Expr = ast.Call(
        name="ifNull",
        args=[ast.Call(name="toString", args=[address]), ast.Constant(value="")],
    )
    is_valid = ast.Or(
        exprs=[
            ast.Call(name="isIPv4String", args=[clone_expr(normalized)]),
            ast.Call(name="isIPv6String", args=[clone_expr(normalized)]),
        ]
    )
    return ast.Call(name="if", args=[is_valid, clone_expr(normalized), ast.Constant(value="::")])
