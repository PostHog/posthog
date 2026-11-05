import pytest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField, TableNode
from posthog.hogql.database.raw_trino_view import RawTrinoViewTable, expand_raw_trino_view_references
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.schema_enums import PersonsOnEventsMode

VIEWS = {
    "__ph_debug_view": "SELECT 1 AS id;",
    "orders_daily": "SELECT * FROM __ph_debug_view -- trailing comment",
    "orders_weekly": "SELECT * FROM orders_daily",
    "orders": "SELECT * FROM cat.sch.orders",
}


@pytest.mark.parametrize(
    "sql,expected",
    [
        (
            "select * from __ph_debug_view",
            'WITH "__ph_debug_view" AS (\nSELECT 1 AS id\n)\nselect * from __ph_debug_view',
        ),
        (
            'select * from "__PH_DEBUG_VIEW"',
            'WITH "__ph_debug_view" AS (\nSELECT 1 AS id\n)\nselect * from "__PH_DEBUG_VIEW"',
        ),
        (
            "-- note\n  with x AS (select 2) select * from x join __ph_debug_view on true",
            '-- note\n  WITH "__ph_debug_view" AS (\nSELECT 1 AS id\n), x AS (select 2) '
            "select * from x join __ph_debug_view on true",
        ),
        (
            "select * from orders_weekly",
            'WITH "__ph_debug_view" AS (\nSELECT 1 AS id\n), '
            '"orders_daily" AS (\nSELECT * FROM __ph_debug_view -- trailing comment\n), '
            '"orders_weekly" AS (\nSELECT * FROM orders_daily\n)\nselect * from orders_weekly',
        ),
        # A view that reads a physical table of its own name does not reference itself.
        ("select * from orders", 'WITH "orders" AS (\nSELECT * FROM cat.sch.orders\n)\nselect * from orders'),
        ("select * from cat.sch.orders_daily", "select * from cat.sch.orders_daily"),
        ("select * from orders_daily_v2", "select * from orders_daily_v2"),
        # The query defines its own CTE with a view's name, so that CTE wins.
        ("with orders AS (select 3) select * from orders", "with orders AS (select 3) select * from orders"),
    ],
)
def test_expands_referenced_views_into_ctes(sql: str, expected: str) -> None:
    assert expand_raw_trino_view_references(sql, VIEWS) == expected


@pytest.mark.parametrize(
    "sql,views,error",
    [
        (
            "select * from view_a",
            {"view_a": "SELECT * FROM view_b", "view_b": "SELECT * FROM view_a"},
            "view_a -> view_b -> view_a",
        ),
        (
            "with recursive t(n) AS (select 1) select * from t, __ph_debug_view",
            VIEWS,
            "WITH RECURSIVE",
        ),
    ],
)
def test_refuses_expansions_trino_cannot_run(sql: str, views: dict[str, str], error: str) -> None:
    with pytest.raises(ExposedHogQLError, match=error):
        expand_raw_trino_view_references(sql, views)


def _context() -> HogQLContext:
    database = Database(include_posthog_tables=False)
    for name in ["__ph_debug_view", "orders_daily"]:
        database.tables.add_child(
            TableNode(
                name=name,
                table=RawTrinoViewTable(
                    name=name,
                    fields={"id": IntegerDatabaseField(name="id")},
                    trino_sql=VIEWS[name],
                    raw_trino_views=VIEWS,
                ),
            )
        )
    return HogQLContext(
        database=database,
        modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        enable_select_queries=True,
        limit_top_select=False,
    )


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SELECT id FROM __ph_debug_view", "(\nSELECT 1 AS id\n)"),
        (
            "SELECT id FROM orders_daily",
            '(\nWITH "__ph_debug_view" AS (\nSELECT 1 AS id\n)\nSELECT * FROM __ph_debug_view -- trailing comment\n)',
        ),
    ],
)
def test_trino_printer_inlines_raw_trino_views(query: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context(), "trino")
    assert expected in sql


@pytest.mark.parametrize("dialect", ["clickhouse", "postgres", "duckdb"])
def test_other_dialects_refuse_raw_trino_views(dialect: str) -> None:
    table = RawTrinoViewTable(name="__ph_debug_view", fields={}, trino_sql="SELECT 1", raw_trino_views={})
    with pytest.raises(QueryError, match="raw Trino SQL"):
        getattr(table, f"to_printed_{dialect}")(HogQLContext())
