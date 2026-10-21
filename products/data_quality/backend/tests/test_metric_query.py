import pytest
from unittest.mock import patch

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery, TableNode
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.resolver import resolve_types

from products.data_catalog.backend.facade.contracts import HogQLMetricDefinition
from products.data_quality.backend.logic.errors import CheckConfigError
from products.data_quality.backend.logic.metric_query import bind_metric_query


def _print(query: ast.SelectQuery | ast.SelectSetQuery) -> str:
    return print_prepared_ast(query, context=HogQLContext(enable_select_queries=True), dialect="hogql")


def test_binds_the_metric_relation_with_its_saved_query_and_constants() -> None:
    """Catches string interpolation leaking saved metric placeholders into a check query."""
    metric = HogQLMetricDefinition(
        query="SELECT count() AS signups FROM events WHERE event = {event_name}",
        values={"event_name": "signup"},
    )

    bound = bind_metric_query("SELECT * FROM {metric} WHERE signups < 100", metric)

    printed = _print(bound)
    assert "FROM (SELECT count() AS signups FROM events WHERE equals(event, 'signup'))" in printed
    assert "WHERE less(signups, 100)" in printed
    assert "{metric}" not in printed
    assert "{event_name}" not in printed


@pytest.mark.parametrize(
    ("check_query", "message"),
    [
        (
            "SELECT * FROM events",
            "Metric custom_sql checks must use exactly one {metric} relation placeholder.",
        ),
        (
            "SELECT * FROM {metric} JOIN {metric} USING id",
            "Metric custom_sql checks must use exactly one {metric} relation placeholder.",
        ),
        (
            "SELECT * FROM {other}",
            "Metric custom_sql checks must use exactly one {metric} relation placeholder.",
        ),
        (
            "SELECT * FROM {metric} WHERE {filters}",
            "Metric custom_sql checks cannot use {filters}.",
        ),
        (
            "SELECT {1 + 1} FROM {metric}",
            "Metric custom_sql checks cannot use expression placeholders.",
        ),
    ],
)
def test_rejects_ambiguous_or_unsafe_metric_check_placeholders(check_query: str, message: str) -> None:
    """Catches a check query binding a metric outside one unambiguous relation position."""
    metric = HogQLMetricDefinition(query="SELECT 1 AS signups", values={})

    with pytest.raises(CheckConfigError, match=f"^{message}$"):
        bind_metric_query(check_query, metric)


@pytest.mark.parametrize(
    ("metric_query", "check_query", "message"),
    [
        (
            "SELECT FROM events",
            "SELECT * FROM {metric}",
            "Could not parse the metric query.",
        ),
        (
            "SELECT 1 AS signups",
            "SELECT * FORM {metric}",
            "Could not parse the metric custom_sql query.",
        ),
    ],
)
def test_hides_parser_internals_for_invalid_metric_or_check_hogql(
    metric_query: str, check_query: str, message: str
) -> None:
    """Catches parser implementation details escaping through metric-check validation."""
    metric = HogQLMetricDefinition(query=metric_query, values={})

    with patch("products.data_quality.backend.logic.metric_query.capture_exception") as capture:
        with pytest.raises(CheckConfigError, match=f"^{message}$"):
            bind_metric_query(check_query, metric)
        capture.assert_not_called()


@pytest.mark.parametrize(
    ("failing_query", "message"),
    [
        ("metric", "Could not parse the metric query."),
        ("check", "Could not parse the metric custom_sql query."),
    ],
)
def test_reports_unexpected_parser_failures_without_exposing_details(failing_query: str, message: str) -> None:
    metric = HogQLMetricDefinition(query="SELECT 1 AS signups", values={})
    parser_error = RuntimeError("Unexpected parser failure with private query contents")
    results = [parser_error] if failing_query == "metric" else [parse_select(metric.query), parser_error]

    with (
        patch("products.data_quality.backend.logic.metric_query.parse_select", side_effect=results),
        patch("products.data_quality.backend.logic.metric_query.capture_exception") as capture,
    ):
        with pytest.raises(CheckConfigError, match=f"^{message}$"):
            bind_metric_query("SELECT * FROM {metric}", metric)
        capture.assert_called_once_with(parser_error)


def test_rejects_cte_metric_reuse() -> None:
    """Catches duplicate metric expansion when a check reuses a CTE."""
    metric = HogQLMetricDefinition(query="SELECT count() AS signups FROM events", values={})

    with pytest.raises(CheckConfigError, match="cannot use CTEs"):
        bind_metric_query(
            "WITH failures AS (SELECT * FROM {metric} WHERE signups < 100) "
            "SELECT * FROM failures UNION ALL SELECT * FROM failures",
            metric,
        )


@pytest.mark.parametrize(
    ("metric_query", "check_query"),
    [
        ("SELECT * FROM orders", "WITH orders AS (SELECT 123 AS total) SELECT * FROM {metric}"),
        (
            "SELECT * FROM orders",
            "WITH orders AS (SELECT 123 AS total) SELECT * FROM orders UNION ALL SELECT * FROM {metric}",
        ),
        ("SELECT * FROM orders", "SELECT * FROM (WITH orders AS (SELECT 123 AS total) SELECT * FROM {metric})"),
        ("SELECT orders AS total", "WITH 123 AS orders SELECT * FROM {metric}"),
        ("SELECT * FROM saved_orders", "WITH orders AS (SELECT 123 AS total) SELECT * FROM {metric}"),
    ],
)
def test_check_ctes_cannot_capture_metric_identifiers(metric_query: str, check_query: str) -> None:
    metric = HogQLMetricDefinition(query=metric_query, values={})
    database = Database()
    database.tables.children["saved_orders"] = TableNode(
        name="saved_orders",
        table=SavedQuery(id="saved-orders", name="saved_orders", query="SELECT * FROM orders", fields={}),
    )
    context = HogQLContext(database=database, enable_select_queries=True)

    with pytest.raises(CheckConfigError, match="cannot use CTEs"):
        resolve_types(bind_metric_query(check_query, metric), context, dialect="hogql")
