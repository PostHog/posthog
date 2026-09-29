"""Bind a metric definition into a custom-SQL failure query without constructing SQL text."""

from collections.abc import Sequence
from typing import cast

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.visitor import TraversingVisitor

from posthog.exceptions_capture import capture_exception

from products.data_catalog.backend.facade.contracts import HogQLMetricDefinition

from .errors import CheckConfigError


class _RelationPlaceholders(TraversingVisitor):
    def __init__(self) -> None:
        self.placeholders: list[ast.Placeholder] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Placeholder):
            self.placeholders.append(node.table)
        super().visit_join_expr(node)


class _MetricCheckCteValidator(TraversingVisitor):
    def visit_cte(self, node: ast.CTE) -> None:
        raise CheckConfigError(
            "Metric custom_sql checks cannot use CTEs. Query {metric} directly or through a subquery."
        )


def bind_metric_query(
    check_query: str, metric_definition: HogQLMetricDefinition
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Return the check query with exactly one metric relation replaced by its saved query AST."""
    metric_placeholders: dict[str, ast.Expr] = {
        name: ast.Constant(value=value) for name, value in metric_definition.values.items()
    }
    metric_query = _parse(metric_definition.query, "Could not parse the metric query.", metric_placeholders)
    check_ast = _parse(check_query, "Could not parse the metric custom_sql query.")
    _validate_metric_placeholder(check_ast)
    _MetricCheckCteValidator().visit(check_ast)
    return cast("ast.SelectQuery | ast.SelectSetQuery", replace_placeholders(check_ast, {"metric": metric_query}))


def _parse(
    query: str, unparseable: str, placeholders: dict[str, ast.Expr] | None = None
) -> ast.SelectQuery | ast.SelectSetQuery:
    try:
        return parse_select(query.rstrip(";").strip(), placeholders=placeholders)
    except ExposedHogQLError:
        raise CheckConfigError(unparseable)
    except Exception as error:
        capture_exception(error)
        raise CheckConfigError(unparseable)


def _validate_metric_placeholder(check_ast: ast.SelectQuery | ast.SelectSetQuery) -> None:
    found = find_placeholders(check_ast)
    if found.has_filters:
        raise CheckConfigError("Metric custom_sql checks cannot use {filters}.")
    if found.placeholder_expressions:
        raise CheckConfigError("Metric custom_sql checks cannot use expression placeholders.")
    if not _has_exactly_one_metric_relation(found.placeholder_fields, check_ast):
        raise CheckConfigError("Metric custom_sql checks must use exactly one {metric} relation placeholder.")


def _has_exactly_one_metric_relation(
    placeholder_fields: Sequence[list[str | int]], check_ast: ast.SelectQuery | ast.SelectSetQuery
) -> bool:
    if placeholder_fields != [["metric"]]:
        return False
    relations = _RelationPlaceholders()
    relations.visit(check_ast)
    return len(relations.placeholders) == 1 and _is_metric_placeholder(relations.placeholders[0])


def _is_metric_placeholder(placeholder: ast.Placeholder) -> bool:
    return isinstance(placeholder.expr, ast.Field) and placeholder.expr.chain == ["metric"]
