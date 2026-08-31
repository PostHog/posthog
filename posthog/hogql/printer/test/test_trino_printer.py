import pytest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import IntegerDatabaseField, StringDatabaseField, StringJSONDatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


def _context() -> HogQLContext:
    database = Database(include_posthog_tables=False)
    for table_name, trino_table_name in (("orders", "order facts"), ("customers", "customers")):
        database.tables.add_child(
            TableNode(
                name=table_name,
                case_insensitive=True,
                table=DirectTrinoTable(
                    name=table_name,
                    fields={
                        "id": IntegerDatabaseField(name="id"),
                        "name": StringDatabaseField(name="name"),
                        "properties": StringJSONDatabaseField(name="properties"),
                    },
                    trino_catalog="iceberg",
                    trino_schema="analytics",
                    trino_table_name=trino_table_name,
                    external_data_source_id="source-id",
                ),
            )
        )
    return HogQLContext(
        team_id=1,
        enable_select_queries=True,
        database=database,
        restricted_properties=set(),
    )


def _print(query: str, context: HogQLContext | None = None) -> tuple[str, HogQLContext]:
    context = context or _context()
    sql, _ = prepare_and_print_ast(parse_select(query, backend="cpp-json"), context, "trino")
    return sql, context


def test_prints_direct_table_and_qmark_parameters() -> None:
    sql, context = _print("SELECT id FROM orders WHERE name = 'Ada'")

    assert sql == (
        'SELECT "orders"."id" FROM "iceberg"."analytics"."order facts" AS "orders" '
        'WHERE ("orders"."name" = ?) LIMIT 50000'
    )
    assert list(context.values.values()) == ["Ada"]


def test_resolves_trino_identifiers_case_insensitively() -> None:
    sql, _ = _print("SELECT ID FROM ORDERS")

    assert 'SELECT "ORDERS"."id" FROM "iceberg"."analytics"."order facts" AS "ORDERS"' in sql


@pytest.mark.parametrize(
    ("query", "expected_suffix"),
    [
        ("SELECT id FROM orders LIMIT 10 OFFSET 4", "OFFSET 4 ROWS LIMIT 10"),
        ("SELECT id FROM orders ORDER BY id LIMIT 10 WITH TIES", "FETCH FIRST 10 ROWS WITH TIES"),
    ],
)
def test_prints_trino_limit_syntax(query: str, expected_suffix: str) -> None:
    sql, _ = _print(query)

    assert sql.endswith(expected_suffix)


def test_prints_trino_limit_syntax_after_set_operation() -> None:
    query = parse_select("SELECT id FROM orders UNION ALL SELECT id FROM orders", backend="cpp-json")
    assert isinstance(query, ast.SelectSetQuery)
    query.limit = ast.Constant(value=10)
    query.offset = ast.Constant(value=4)
    sql, _ = prepare_and_print_ast(query, _context(), "trino")

    assert sql.endswith("OFFSET 4 ROWS LIMIT 10")


@pytest.mark.parametrize("operator", ["INTERSECT", "INTERSECT ALL", "EXCEPT", "EXCEPT ALL"])
def test_prints_trino_set_operators(operator: str) -> None:
    sql, _ = _print(f"SELECT id FROM orders {operator} SELECT id FROM orders")

    assert f" {operator} " in sql


@pytest.mark.parametrize(
    ("query", "expected_fragment"),
    [
        ("SELECT [1, 2, 3][1:2] FROM orders", "slice(ARRAY[1, 2, 3], 1, greatest(0, (2) - (1) + 1))"),
        ("SELECT toString(id) FROM orders", 'CAST("orders"."id" AS VARCHAR)'),
        ("SELECT countIf(id > 0) FROM orders", 'count(*) FILTER (WHERE ("orders"."id" > 0))'),
        ("SELECT name ILIKE 'ada%' FROM orders", 'lower("orders"."name") LIKE lower(?)'),
        ("SELECT position(name, 'd') FROM orders", 'strpos("orders"."name", ?)'),
        ("SELECT CAST([1] AS Array(String)) FROM orders", "CAST(ARRAY[1] AS ARRAY(VARCHAR))"),
        ("SELECT CAST(id AS timestamp(0)) FROM orders", 'CAST("orders"."id" AS TIMESTAMP(0))'),
        ("SELECT id, count() FROM orders GROUP BY ALL", "GROUP BY AUTO"),
        ("SELECT id FROM orders ORDER BY #1", "ORDER BY 1 ASC"),
        ("SELECT uniq(id, name) FROM orders", 'count(DISTINCT ROW("orders"."id", "orders"."name"))'),
        ("SELECT toDecimal(id, 2) FROM orders", 'CAST("orders"."id" AS DECIMAL(18,2))'),
        ("SELECT toDateTime64(name, 6) FROM orders", 'CAST("orders"."name" AS TIMESTAMP(6))'),
        (
            "SELECT toIntOrDefault(name, 7) FROM orders",
            'COALESCE(TRY_CAST("orders"."name" AS BIGINT), CAST(7 AS BIGINT))',
        ),
        ("SELECT arrayMap(x -> x + 1, [1, 2]) FROM orders", 'transform(ARRAY[1, 2], "x" -> ("x" + 1))'),
        ("SELECT arrayFilter(x -> x > 1, [1, 2]) FROM orders", 'filter(ARRAY[1, 2], "x" -> ("x" > 1))'),
        ("SELECT tuple(id, name) FROM orders", 'ROW("orders"."id", "orders"."name")'),
        ("SELECT tupleElement(tuple(id, name), 2) FROM orders", '(ROW("orders"."id", "orders"."name"))[2]'),
        (
            "SELECT dateTrunc('month', toDateTime(name, 'UTC')) FROM orders",
            'date_trunc(?, with_timezone(CAST("orders"."name" AS TIMESTAMP), ?))',
        ),
        ("SELECT extract(name, '([a-z]+)') FROM orders", 'regexp_extract("orders"."name", ?)'),
        ("SELECT groupUniqArray(name) FROM orders", 'array_distinct(array_agg("orders"."name"))'),
        (
            "SELECT groupUniqArrayIf(name, id > 0) FROM orders",
            'array_distinct(array_agg("orders"."name") FILTER (WHERE ("orders"."id" > 0)))',
        ),
        (
            "SELECT argMaxIf(name, id, id > 0) FROM orders",
            'max_by("orders"."name", "orders"."id") FILTER (WHERE ("orders"."id" > 0))',
        ),
        ("SELECT arrayElement([1, 2], -1) FROM orders", "element_at(ARRAY[1, 2], -1)"),
        (
            "SELECT arrayFirst(x -> x > 1, [1, 2]) FROM orders",
            'element_at(filter(ARRAY[1, 2], "x" -> ("x" > 1)), 1)',
        ),
        ("SELECT extractAll(name, '([a-z]+)') FROM orders", 'regexp_extract_all("orders"."name", ?)'),
        ("SELECT multiplyDecimal(id, 100) FROM orders", '("orders"."id" * 100)'),
        (
            "SELECT intDiv(id, 1000) FROM orders",
            'CAST(floor(CAST("orders"."id" AS DOUBLE) / 1000) AS BIGINT)',
        ),
        ("SELECT md5(name) FROM orders", 'to_hex(md5(to_utf8(CAST("orders"."name" AS VARCHAR))))'),
        ("SELECT md5(name AS TEXT) FROM orders", 'to_hex(md5(to_utf8(CAST("orders"."name" AS VARCHAR))))'),
        ("SELECT arrayMin([1, 2]) FROM orders", "array_min(ARRAY[1, 2])"),
        ("SELECT greaterOrEquals(id, 1) FROM orders", '("orders"."id" >= 1)'),
        ("SELECT in(id, (1, 2)) FROM orders", '("orders"."id" IN (1, 2))'),
        (
            "SELECT dateAdd(toDate('2026-01-01'), toIntervalMonth(1)) FROM orders",
            "(CAST(? AS DATE) + (1 * INTERVAL '1' MONTH))",
        ),
        ("SELECT current_timestamp() FROM orders", "CURRENT_TIMESTAMP"),
        (
            "SELECT toTimeZone(toDateTime(name), 'America/New_York') FROM orders",
            'at_timezone(with_timezone(CAST(CAST("orders"."name" AS TIMESTAMP) AS TIMESTAMP), \'UTC\'), ?)',
        ),
        ("SELECT JSONHas(properties, 'segment') FROM orders", '(json_extract("orders"."properties", ?) IS NOT NULL)'),
        (
            "SELECT JSONExtract(properties, 'Map(String, Float64)') FROM orders",
            'CAST(json_extract("orders"."properties", \'$\') AS MAP(VARCHAR, DOUBLE))',
        ),
        (
            "SELECT JSONExtractKeys(properties) FROM orders",
            'map_keys(CAST(json_extract("orders"."properties", ?) AS MAP(VARCHAR, JSON)))',
        ),
        (
            "SELECT JSONExtractKeysAndValues(properties, 'Float64') FROM orders",
            'map_entries(CAST(json_extract("orders"."properties", ?) AS MAP(VARCHAR, DOUBLE)))',
        ),
        (
            "SELECT JSONExtractKeysAndValuesRaw(properties) FROM orders",
            'map_entries(CAST(json_extract("orders"."properties", ?) AS MAP(VARCHAR, JSON)))',
        ),
        ("SELECT quantile(0.9)(id) FROM orders", 'approx_percentile("orders"."id", 0.9)'),
        (
            "SELECT quantileIf(0.9)(id, id > 0) FROM orders",
            'approx_percentile("orders"."id", 0.9) FILTER (WHERE ("orders"."id" > 0))',
        ),
        (
            "SELECT groupArrayIf(10)(name, id > 0) FROM orders",
            'slice(array_agg("orders"."name") FILTER (WHERE ("orders"."id" > 0)), 1, 10)',
        ),
        (
            "SELECT date_part('year', toDateTime(name)) FROM orders",
            'EXTRACT(YEAR FROM CAST("orders"."name" AS TIMESTAMP))',
        ),
        (
            "SELECT orders.id FROM orders LEFT JOIN customers ON orders.id = customers.id",
            'LEFT JOIN "iceberg"."analytics"."customers" AS "customers" ON ("orders"."id" = "customers"."id")',
        ),
        (
            "SELECT t.a FROM (SELECT id FROM orders) AS t(a)",
            'AS "t" ("a")',
        ),
    ],
)
def test_prints_trino_expressions(query: str, expected_fragment: str) -> None:
    sql, _ = _print(query)

    assert expected_fragment in sql


def test_prints_json_property_access_as_bound_json_path() -> None:
    sql, context = _print("SELECT properties.customer.name FROM orders")

    assert 'json_extract_scalar("orders"."properties", ?)' in sql
    assert list(context.values.values()) == ['$."customer"."name"']


def test_array_slice_does_not_duplicate_bound_parameters() -> None:
    sql, context = _print("SELECT ['a', 'b'][2:] FROM orders")

    assert "slice(ARRAY[?, ?], 2, 2147483647)" in sql
    assert sql.count("?") == len(context.values) == 2


@pytest.mark.parametrize(
    ("query", "expected_fragment"),
    [
        (
            "SELECT row_number() OVER (ORDER BY id) FROM orders",
            'row_number() OVER (ORDER BY "orders"."id" ASC)',
        ),
        (
            "SELECT groupArray(name) OVER (ORDER BY id) FROM orders",
            'array_agg("orders"."name") OVER (ORDER BY "orders"."id" ASC)',
        ),
        (
            "SELECT countIf(id > 0) OVER (ORDER BY id) FROM orders",
            'count(*) FILTER (WHERE ("orders"."id" > 0)) OVER (ORDER BY "orders"."id" ASC)',
        ),
        (
            "SELECT lag(name) OVER ordered FROM orders WINDOW ordered AS (ORDER BY id)",
            'lag("orders"."name") OVER "ordered"',
        ),
        (
            "SELECT lagInFrame(name, 1, 'missing') OVER (ORDER BY id) FROM orders",
            'lag("orders"."name", 1, ?) OVER (ORDER BY "orders"."id" ASC)',
        ),
        (
            "SELECT countDistinct(name) OVER () FROM orders",
            'count(DISTINCT "orders"."name") OVER ()',
        ),
    ],
)
def test_prints_trino_window_functions(query: str, expected_fragment: str) -> None:
    sql, _ = _print(query)

    assert expected_fragment in sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT empty('a') FROM orders",
        "SELECT toStartOfFiveMinutes(toDateTime('2026-01-02 03:04:05')) FROM orders",
    ],
)
def test_parameterized_rewrites_keep_qmarks_and_values_aligned(query: str) -> None:
    sql, context = _print(query)

    assert sql.count("?") == len(context.values) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM orders PREWHERE id > 0",
        "SELECT id FROM orders QUALIFY id > 0",
        "SELECT id FROM orders LIMIT 10 BY name",
        "SELECT id FROM orders ORDER BY id WITH FILL",
        "SELECT id FROM orders LIMIT 10 WITH TIES",
        "SELECT orders.id FROM orders LEFT ANY JOIN customers ON orders.id = customers.id",
        "SELECT quantiles(0.5)(id) OVER () FROM orders",
        "SELECT lag(name) OVER () FROM orders",
        "SELECT row_number() OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM orders",
        "WITH 1 AS scalar_value SELECT scalar_value FROM orders",
        "SELECT * FROM orders PIVOT(count(id) FOR name IN ('a'))",
        "SELECT * FROM orders UNPIVOT(value FOR key IN (id))",
        "SELECT arrayMap((x, y) -> x + y, [1], [2]) FROM orders",
    ],
)
def test_rejects_hogql_clauses_without_trino_equivalents(query: str) -> None:
    with pytest.raises(QueryError):
        _print(query)


def test_rejects_set_with_ties_without_outer_ordering() -> None:
    query = parse_select("SELECT id FROM orders UNION ALL SELECT id FROM orders", backend="cpp-json")
    assert isinstance(query, ast.SelectSetQuery)
    query.limit = ast.Constant(value=10)
    query.limit_with_ties = True

    with pytest.raises(QueryError):
        prepare_and_print_ast(query, _context(), "trino")


def test_rejects_non_literal_limit_that_trino_cannot_parse() -> None:
    query = parse_select("SELECT id FROM orders", backend="cpp-json")
    assert isinstance(query, ast.SelectQuery)
    query.limit = ast.Call(name="least", args=[ast.Constant(value=10), ast.Constant(value=20)])

    with pytest.raises(QueryError):
        prepare_and_print_ast(query, _context(), "trino")


@pytest.mark.parametrize("modifier", ["distinct", "filter"])
def test_rejects_aggregate_only_modifiers_on_scalar_calls(modifier: str) -> None:
    query = parse_select("SELECT toDecimal(id, 2) FROM orders", backend="cpp-json")
    assert isinstance(query, ast.SelectQuery)
    call = query.select[0]
    assert isinstance(call, ast.Call)
    if modifier == "distinct":
        call.distinct = True
    else:
        call.filter_expr = ast.Constant(value=True)

    with pytest.raises(QueryError):
        prepare_and_print_ast(query, _context(), "trino")


@pytest.mark.parametrize(
    "type_name",
    [
        "varchar); DROP TABLE users; --",
        "decimal(39,0)",
        "decimal(2,3)",
        "timestamp(13)",
        "char(1,2)",
    ],
)
def test_rejects_invalid_cast_type_name(type_name: str) -> None:
    context = _context()
    query = parse_select("SELECT id FROM orders", backend="cpp-json")
    assert isinstance(query, ast.SelectQuery)
    query.select[0] = ast.TypeCast(expr=query.select[0], type_name=type_name)

    with pytest.raises(QueryError):
        prepare_and_print_ast(query, context, "trino")
