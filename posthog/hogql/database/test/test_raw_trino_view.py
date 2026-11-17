import pytest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField, TableNode
from posthog.hogql.database.raw_trino_view import RawTrinoViewTable
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.schema_enums import PersonsOnEventsMode

VIEWS = {
    "daily": "SELECT 1 AS x; -- note",
    "reports.daily": "SELECT 2 AS x",
    "reads_orders": "SELECT * FROM orders",
    "breaks_out": "SELECT 1) x, (SELECT 2",
    "two_statements": "SELECT 1; SELECT 2",
}


def _context(*, access: bool = True) -> HogQLContext:
    database = Database(include_posthog_tables=False)
    for name, sql in VIEWS.items():
        table = RawTrinoViewTable(name=name, fields={"x": IntegerDatabaseField(name="x")}, sql=sql if access else None)
        database.tables.add_child(TableNode.create_nested_for_chain(name.split("."), table=table))
    return HogQLContext(
        database=database,
        modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        enable_select_queries=True,
        limit_top_select=False,
        use_new_events_schema=False,
    )


DAILY = "__ph_rv_0 AS (\nSELECT 1 AS x\n)"


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "WITH orders AS (SELECT 9 AS x) SELECT orders.x FROM orders JOIN reads_orders ON true",
            'WITH __ph_rv_0 AS (\nSELECT * FROM orders\n), "orders" AS (SELECT 9 AS "x") '
            'SELECT "orders"."x" FROM "orders" JOIN __ph_rv_0 AS "reads_orders" ON true',
        ),
        (
            "SELECT d.x FROM daily d JOIN daily ON true",
            f'WITH {DAILY}\nSELECT "d"."x" FROM __ph_rv_0 AS "d" JOIN __ph_rv_0 AS "daily" ON true',
        ),
        (
            "SELECT x FROM reports.daily",
            'WITH __ph_rv_0 AS (\nSELECT 2 AS x\n)\nSELECT "reports__daily"."x" FROM __ph_rv_0 AS "reports__daily"',
        ),
    ],
)
def test_trino_printer_hoists_raw_trino_views_before_the_query_ctes(query: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context(), "trino")
    assert sql == expected


@pytest.mark.parametrize(
    "query,access,error",
    [
        ("SELECT x FROM daily", False, "Open it from the SQL editor while signed in"),
        ("WITH RECURSIVE t AS (SELECT 1 AS n) SELECT x FROM t, daily", True, "WITH RECURSIVE"),
        (
            "SELECT x FROM daily WHERE x IN (WITH __PH_RV_0 AS (SELECT 1 AS x) SELECT x FROM __PH_RV_0)",
            True,
            "reserved",
        ),
        ("SELECT x FROM breaks_out", True, "unbalanced parentheses"),
        ("SELECT x FROM two_statements", True, "single SELECT statement"),
    ],
)
def test_trino_printer_refuses_raw_trino_views_it_cannot_inline(query: str, access: bool, error: str) -> None:
    with pytest.raises((ExposedHogQLError, QueryError), match=error):
        prepare_and_print_ast(parse_select(query), _context(access=access), "trino")


@pytest.mark.parametrize("dialect", ["postgres", "duckdb"])
def test_other_dialects_refuse_raw_trino_views(dialect: str) -> None:
    with pytest.raises(QueryError, match="runs raw Trino SQL"):
        prepare_and_print_ast(parse_select("SELECT x FROM daily"), _context(), dialect)  # type: ignore[arg-type]
