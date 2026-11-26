from collections.abc import Callable

from posthog.hogql import ast
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.visitor import TraversingVisitor


class _AggregateCollector(TraversingVisitor):
    def __init__(self, is_hoisted: Callable[[ast.Call], bool]) -> None:
        super().__init__()
        self.is_hoisted = is_hoisted
        self.aggregates: list[ast.Call] = []
        self.lambda_depth = 0
        self.in_lambda = False
        self.reads_lambda_argument = False

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        pass

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.lambda_depth += 1
        try:
            super().visit_lambda(node)
        finally:
            self.lambda_depth -= 1

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name) is None or self.is_hoisted(node):
            super().visit_call(node)
            return
        self.aggregates.append(node)
        self.in_lambda = self.in_lambda or self.lambda_depth > 0
        finder = _LambdaArgumentFinder()
        finder.visit(node)
        self.reads_lambda_argument = self.reads_lambda_argument or finder.found


class _LambdaArgumentFinder(TraversingVisitor):
    found: bool = False

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_field(self, node: ast.Field) -> None:
        if isinstance(node.type, ast.LambdaArgumentType):
            self.found = True


def aggregates_to_hoist(call: ast.Call, is_hoisted: Callable[[ast.Call], bool]) -> list[ast.Call]:
    """The aggregates of a call to compute outside it, because one of them sits in a lambda body.

    Trino rejects an aggregate inside a lambda. The printer computes them once, passes them into a one-element
    `transform` as a ROW, and prints the call inside that lambda, so every aggregate of the call has to move out.
    """
    if find_hogql_aggregation(call.name) is not None or not any(isinstance(arg, ast.Lambda) for arg in call.args):
        return []
    collector = _AggregateCollector(is_hoisted)
    for arg in call.args:
        collector.visit(arg)
    # An aggregate over a lambda argument can't be computed outside the lambda, and ClickHouse rejects it too.
    if not collector.in_lambda or collector.reads_lambda_argument:
        return []
    return collector.aggregates
