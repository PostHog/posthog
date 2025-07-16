from typing import Literal, Optional, cast
from collections.abc import Callable

from antlr4.error.ErrorListener import ErrorListener
from prometheus_client import Histogram

from posthog.hogql import ast
from posthog.hogql.errors import SyntaxError
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.timings import HogQLTimings
from hogql_parser import (
    parse_expr as _parse_expr_cpp,
    parse_order_expr as _parse_order_expr_cpp,
    parse_select as _parse_select_cpp,
    parse_full_template_string as _parse_full_template_string_cpp,
    parse_program as _parse_program_cpp,
)


def safe_lambda(f):
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            if str(e) == "Empty Stack":  # Antlr throws `Exception("Empty Stack")` ¯\_(ツ)_/¯
                raise SyntaxError("Unmatched curly bracket") from e
            raise

    return wrapped


RULE_TO_PARSE_FUNCTION: dict[
    Literal["cpp"], dict[Literal["expr", "order_expr", "select", "full_template_string", "program"], Callable]
] = {
    "cpp": {
        "expr": lambda string, start: _parse_expr_cpp(string, is_internal=start is None),
        "order_expr": lambda string: _parse_order_expr_cpp(string),
        "select": lambda string: _parse_select_cpp(string),
        "full_template_string": lambda string: _parse_full_template_string_cpp(string),
        "program": lambda string: _parse_program_cpp(string),
    },
}

RULE_TO_HISTOGRAM: dict[Literal["expr", "order_expr", "select", "full_template_string"], Histogram] = {
    cast(Literal["expr", "order_expr", "select", "full_template_string"], rule): Histogram(
        f"parse_{rule}_seconds",
        f"Time to parse {rule} expression",
        labelnames=["backend"],
    )
    for rule in ("expr", "order_expr", "select", "full_template_string")
}


def parse_string_template(
    string: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["cpp"] = "cpp",
) -> ast.Call:
    """Parse a full template string without start/end quotes"""
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_full_template_string_{backend}"):
        with RULE_TO_HISTOGRAM["full_template_string"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["full_template_string"]("F'" + string)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_expr(
    expr: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    start: Optional[int] = 0,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["cpp"] = "cpp",
) -> ast.Expr:
    if expr == "":
        raise SyntaxError("Empty query")
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_expr_{backend}"):
        with RULE_TO_HISTOGRAM["expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["expr"](expr, start)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_order_expr(
    order_expr: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["cpp"] = "cpp",
) -> ast.OrderExpr:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_order_expr_{backend}"):
        with RULE_TO_HISTOGRAM["order_expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["order_expr"](order_expr)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_select(
    statement: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["cpp"] = "cpp",
) -> ast.SelectQuery | ast.SelectSetQuery:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_select_{backend}"):
        with RULE_TO_HISTOGRAM["select"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["select"](statement)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_program(
    source: str,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["cpp"] = "cpp",
) -> ast.Program:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_expr_{backend}"):
        with RULE_TO_HISTOGRAM["expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["program"](source)
    return node


class HogQLErrorListener(ErrorListener):
    query: str

    def __init__(self, query: str = ""):
        super().__init__()
        self.query = query

    def get_position(self, line, column):
        lines = self.query.split("\n")
        try:
            position = sum(len(lines[i]) + 1 for i in range(line - 1)) + column
        except IndexError:
            return -1
        if position > len(self.query):
            return -1
        return position

    def syntaxError(self, recognizer, offendingType, line, column, msg, e):
        start = max(self.get_position(line, column), 0)
        raise SyntaxError(msg, start=start, end=len(self.query))
