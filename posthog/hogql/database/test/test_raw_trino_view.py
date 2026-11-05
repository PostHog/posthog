import pytest
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField, TableNode
from posthog.hogql.database.raw_trino_view import (
    RawTrinoView,
    RawTrinoViewCatalog,
    RawTrinoViewTable,
    RefusedRawTrinoViewTable,
    expand_raw_trino_view_references,
)
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.schema_enums import PersonsOnEventsMode


def _catalog(views: dict[str, str], **names: frozenset[str]) -> RawTrinoViewCatalog:
    return RawTrinoViewCatalog(
        views={name.lower(): RawTrinoView(name=name, sql=sql) for name, sql in views.items()}, **names
    )


CATALOG = _catalog(
    {
        "daily": "SELECT 1 AS x; -- note",
        "reports.daily": "SELECT 2 AS y",
        "helper": "SELECT 3 AS h",
        "uses_helper": "SELECT * FROM helper",
        "reads_orders": "SELECT * FROM orders",
        "with_body": "WITH h AS (SELECT 4 AS z) SELECT * FROM h ORDER BY z LIMIT 1",
        "a": "SELECT * FROM b JOIN c ON true",
        "b": "SELECT * FROM d",
        "c": "SELECT * FROM d",
        "d": "SELECT 5 AS z",
        "self_alias": "SELECT 1 AS self_alias FROM d",
        "reads_secret": "SELECT * FROM secret",
        "reads_hogql": "SELECT * FROM hogql_view",
        "reads_gone": "SELECT * FROM gone",
        "reads_real": "SELECT * FROM real_table",
    },
    denied_names=frozenset({"secret"}),
    hogql_view_names=frozenset({"hogql_view"}),
    deleted_names=frozenset({"gone"}),
)

DAILY = "__ph_rv_0 AS (\nSELECT 1 AS x\n)"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) AS daily FROM t",
        "SELECT 'daily' FROM t",
        "SELECT 1 FROM t -- daily",
        "SELECT /* daily */ 1 FROM t",
        "SELECT * FROM cat.sch.daily",
        "SELECT * FROM sch.daily",
        "WITH daily AS (SELECT 5) SELECT * FROM daily",
        "WITH RECURSIVE t(n) AS (SELECT 1) SELECT * FROM t",
        "SELECT * FROM real_table",
        "SELECT * FROM gone",
        "this is not sql at all",
    ],
)
def test_leaves_sql_without_view_references_unchanged(sql: str) -> None:
    assert expand_raw_trino_view_references(sql, CATALOG) == sql


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT daily.x FROM daily", f'WITH {DAILY}\nSELECT daily.x FROM __ph_rv_0 AS "daily"'),
        ('SELECT d.x FROM "DAILY" d', f"WITH {DAILY}\nSELECT d.x FROM __ph_rv_0 d"),
        (
            "SELECT * FROM daily JOIN daily d2 ON true",
            f'WITH {DAILY}\nSELECT * FROM __ph_rv_0 AS "daily" JOIN __ph_rv_0 d2 ON true',
        ),
        (
            "SELECT * FROM t WHERE id IN (SELECT x FROM daily) AND EXISTS (SELECT 1 FROM daily)",
            f'WITH {DAILY}\nSELECT * FROM t WHERE id IN (SELECT x FROM __ph_rv_0 AS "daily") '
            'AND EXISTS (SELECT 1 FROM __ph_rv_0 AS "daily")',
        ),
        (
            "SELECT * FROM t, LATERAL (SELECT * FROM daily) l",
            f'WITH {DAILY}\nSELECT * FROM t, LATERAL (SELECT * FROM __ph_rv_0 AS "daily") l',
        ),
        (
            "SELECT 1 UNION ALL SELECT x FROM daily",
            f'WITH {DAILY}\nSELECT 1 UNION ALL SELECT x FROM __ph_rv_0 AS "daily"',
        ),
        (
            "-- c\n/* d */ WITH mine AS (SELECT * FROM daily) SELECT * FROM mine",
            f'-- c\n/* d */ WITH {DAILY}, mine AS (SELECT * FROM __ph_rv_0 AS "daily") SELECT * FROM mine',
        ),
        (
            "SELECT * FROM (WITH daily AS (SELECT 5) SELECT * FROM daily) JOIN daily ON true",
            f'WITH {DAILY}\nSELECT * FROM (WITH daily AS (SELECT 5) SELECT * FROM daily) JOIN __ph_rv_0 AS "daily" ON true',
        ),
        (
            "WITH helper AS (SELECT 9) SELECT * FROM helper, uses_helper",
            'WITH __ph_rv_0 AS (\nSELECT 3 AS h\n), __ph_rv_1 AS (\nSELECT * FROM __ph_rv_0 AS "helper"\n), '
            'helper AS (SELECT 9) SELECT * FROM helper, __ph_rv_1 AS "uses_helper"',
        ),
        (
            "WITH orders AS (SELECT 9) SELECT * FROM orders, reads_orders",
            "WITH __ph_rv_0 AS (\nSELECT * FROM orders\n), "
            'orders AS (SELECT 9) SELECT * FROM orders, __ph_rv_0 AS "reads_orders"',
        ),
        (
            "SELECT * FROM with_body",
            'WITH __ph_rv_0 AS (\nWITH h AS (SELECT 4 AS z) SELECT * FROM h ORDER BY z LIMIT 1\n)\nSELECT * FROM __ph_rv_0 AS "with_body"',
        ),
        (
            'SELECT * FROM reports.daily, "reports.daily" r',
            'WITH __ph_rv_0 AS (\nSELECT 2 AS y\n)\nSELECT * FROM __ph_rv_0 AS "daily", __ph_rv_0 r',
        ),
        (
            "SELECT * FROM a",
            "WITH __ph_rv_0 AS (\nSELECT 5 AS z\n), "
            '__ph_rv_1 AS (\nSELECT * FROM __ph_rv_0 AS "d"\n), '
            '__ph_rv_2 AS (\nSELECT * FROM __ph_rv_0 AS "d"\n), '
            '__ph_rv_3 AS (\nSELECT * FROM __ph_rv_1 AS "b" JOIN __ph_rv_2 AS "c" ON true\n)\n'
            'SELECT * FROM __ph_rv_3 AS "a"',
        ),
        (
            "SELECT * FROM self_alias",
            'WITH __ph_rv_0 AS (\nSELECT 5 AS z\n), __ph_rv_1 AS (\nSELECT 1 AS self_alias FROM __ph_rv_0 AS "d"\n)\n'
            'SELECT * FROM __ph_rv_1 AS "self_alias"',
        ),
        (
            "SELECT * FROM reads_real",
            'WITH __ph_rv_0 AS (\nSELECT * FROM real_table\n)\nSELECT * FROM __ph_rv_0 AS "reads_real"',
        ),
    ],
)
def test_hoists_each_referenced_view_once(sql: str, expected: str) -> None:
    assert expand_raw_trino_view_references(sql, CATALOG) == expected


@pytest.mark.parametrize(
    "sql,catalog,error",
    [
        ("WITH RECURSIVE t(n) AS (SELECT 1) SELECT * FROM t, daily", CATALOG, "WITH RECURSIVE"),
        ("SELECT * FROM __ph_rv_0", CATALOG, "reserved"),
        ("SELECT * FROM secret", CATALOG, "don't have access to view 'secret'"),
        ("SELECT * FROM reads_secret", CATALOG, "don't have access to view 'secret'"),
        ("SELECT * FROM reads_hogql", CATALOG, "'hogql_view' is a HogQL view"),
        ("SELECT * FROM reads_gone", CATALOG, "reads view 'gone', which was deleted"),
        ("SELECT FROM WHERE daily", CATALOG, "Could not parse the query to expand view 'daily'"),
        (
            "SELECT * FROM view_a",
            _catalog({"view_a": "SELECT * FROM view_b", "view_b": "SELECT * FROM view_a"}),
            "view_a -> view_b -> view_a",
        ),
        (
            "SELECT * FROM v0",
            _catalog({f"v{i}": f"SELECT * FROM v{i + 1}" for i in range(40)} | {"v40": "SELECT 1"}),
            "nested more than",
        ),
    ],
)
def test_refuses_expansions_trino_cannot_run(sql: str, catalog: RawTrinoViewCatalog, error: str) -> None:
    with pytest.raises(ExposedHogQLError, match=error):
        expand_raw_trino_view_references(sql, catalog)


def test_refuses_expansions_over_the_size_cap() -> None:
    with (
        patch("posthog.hogql.database.raw_trino_view.MAX_EXPANDED_SQL_LENGTH", 20),
        pytest.raises(ExposedHogQLError, match="too much SQL"),
    ):
        expand_raw_trino_view_references("SELECT * FROM a", CATALOG)


def test_many_leading_comments_do_not_backtrack() -> None:
    sql = "/**/" * 30 + " WITH t AS (SELECT 1) SELECT * FROM t, daily"
    assert expand_raw_trino_view_references(sql, CATALOG) == (
        "/**/" * 30 + f' WITH {DAILY}, t AS (SELECT 1) SELECT * FROM t, __ph_rv_0 AS "daily"'
    )


def _context(
    catalog: RawTrinoViewCatalog | None, table_class: type[RawTrinoViewTable] = RawTrinoViewTable
) -> HogQLContext:
    database = Database(include_posthog_tables=False)
    for name in ["daily", "reports.daily", "a", "reads_hogql"]:
        database.tables.add_child(
            TableNode.create_nested_for_chain(
                name.split("."), table=table_class(name=name, fields={"x": IntegerDatabaseField(name="x")})
            )
        )
    database._raw_trino_view_catalog = catalog
    return HogQLContext(
        database=database,
        modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        enable_select_queries=True,
        limit_top_select=False,
    )


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SELECT x FROM daily", 'SELECT "daily"."x" FROM (\nSELECT 1 AS x\n) AS "daily"'),
        (
            "SELECT x FROM reports.daily",
            'SELECT "reports__daily"."x" FROM (\nSELECT 2 AS y\n) AS "reports__daily"',
        ),
        (
            "SELECT x FROM a",
            'SELECT "a"."x" FROM (\nWITH __ph_rv_0 AS (\nSELECT 5 AS z\n), '
            '__ph_rv_1 AS (\nSELECT * FROM __ph_rv_0 AS "d"\n), '
            '__ph_rv_2 AS (\nSELECT * FROM __ph_rv_0 AS "d"\n)\n'
            'SELECT * FROM __ph_rv_1 AS "b" JOIN __ph_rv_2 AS "c" ON true\n) AS "a"',
        ),
    ],
)
def test_trino_printer_inlines_raw_trino_views(query: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context(CATALOG), "trino")
    assert sql == expected


@pytest.mark.parametrize(
    "catalog,table_class,error",
    [
        (CATALOG, RefusedRawTrinoViewTable, "Open it from the SQL editor while signed in"),
        (None, RawTrinoViewTable, "which this query cannot read"),
        (CATALOG, RawTrinoViewTable, "'hogql_view' is a HogQL view"),
    ],
)
def test_trino_printer_refuses_raw_trino_views_it_cannot_expand(
    catalog: RawTrinoViewCatalog | None, table_class: type[RawTrinoViewTable], error: str
) -> None:
    query = "SELECT x FROM reads_hogql" if table_class is RawTrinoViewTable and catalog else "SELECT x FROM daily"
    with pytest.raises((ExposedHogQLError, QueryError), match=error):
        prepare_and_print_ast(parse_select(query), _context(catalog, table_class), "trino")


@pytest.mark.parametrize("dialect", ["clickhouse", "postgres", "duckdb"])
def test_other_dialects_refuse_raw_trino_views(dialect: str) -> None:
    table = RawTrinoViewTable(name="daily", fields={})
    with pytest.raises(QueryError, match="raw Trino SQL"):
        getattr(table, f"to_printed_{dialect}")(HogQLContext())
