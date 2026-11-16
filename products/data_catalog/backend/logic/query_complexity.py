"""Rate how hard a query is to write by hand, so the proposals that most need one shared definition come first.

A count of one event takes seconds to write again. A query with joins, subqueries, window functions or
conditional aggregates takes real work, and two people rarely write it the same way.
"""

from enum import IntEnum

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.visitor import TraversingVisitor

from .measure_fingerprint import MeasureFingerprint


class Complexity(IntEnum):
    UNKNOWN = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


_MEDIUM_SCORE = 2
_HIGH_SCORE = 5
_CONDITIONAL_CALLS = frozenset({"if", "multiif"})
# A normalized aggregate writes arithmetic as calls, such as divide(a, b).
_ARITHMETIC_CALLS = frozenset({"plus", "minus", "multiply", "divide", "intdiv", "modulo"})


class _Counter(TraversingVisitor):
    def __init__(self) -> None:
        self.selects = 0
        self.joins = 0
        self.windows = 0
        self.conditionals = 0
        self.calculations = 0
        self.lambdas = 0

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects += 1
        super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.join_type:
            self.joins += 1
        super().visit_join_expr(node)

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.windows += 1
        super().visit_window_function(node)

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        if name in _CONDITIONAL_CALLS or (name.endswith("if") and len(name) > 2):
            self.conditionals += 1
        elif name in _ARITHMETIC_CALLS:
            self.calculations += 1
        super().visit_call(node)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> None:
        self.calculations += 1
        super().visit_arithmetic_operation(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.lambdas += 1
        super().visit_lambda(node)


def _tier(score: int) -> Complexity:
    if score >= _HIGH_SCORE:
        return Complexity.HIGH
    return Complexity.MEDIUM if score >= _MEDIUM_SCORE else Complexity.LOW


def measure_complexity(measure: MeasureFingerprint) -> Complexity:
    """Rate one measure, not the query it came from: a plain count inside a large query is still simple."""
    try:
        aggregate = parse_expr(measure.aggregate)
    except BaseHogQLError:
        return Complexity.UNKNOWN
    counter = _Counter()
    counter.visit(aggregate)
    score = (
        2 * max(0, len(measure.tables) - 1)
        + min(counter.conditionals, 3)
        + min(counter.calculations, 2)
        + min(counter.lambdas, 2)
        + 2 * counter.windows
        + min(max(0, len(measure.predicate) - 1), 2)
    )
    return _tier(score)


def query_complexity(sql: str) -> Complexity:
    """Rate a whole query, such as a drafted definition. Joins, subqueries and window functions weigh most."""
    try:
        node = parse_select(sql)
    except BaseHogQLError:
        return Complexity.UNKNOWN
    counter = _Counter()
    counter.visit(node)
    score = (
        2 * counter.joins
        + 2 * max(0, counter.selects - 1)
        + 2 * counter.windows
        + min(counter.conditionals, 3)
        + min(counter.calculations, 2)
        + min(counter.lambdas, 2)
    )
    return _tier(score)
