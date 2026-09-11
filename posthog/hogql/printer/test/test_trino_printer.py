import sqlite3
from contextlib import closing

import pytest
from unittest import mock

from syrupy.assertion import SnapshotAssertion

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    IntegerDatabaseField,
    SavedQuery,
    StringDatabaseField,
    StringJSONDatabaseField,
    TableNode,
    UUIDDatabaseField,
)
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.helpers.timestamp_visitor import is_time_or_interval_constant
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.transpiler import TrinoTranspilerInput, transpile_prepared_hogql_to_trino
from posthog.hogql.transforms.trino.validate import _SPECIAL_CALLS
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.schema_enums import PersonsOnEventsMode


def _trino_modifiers() -> HogQLQueryModifiers:
    return HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)


def _context_with_trino_table() -> HogQLContext:
    database = Database(include_posthog_tables=False)
    database.tables.add_child(
        TableNode(
            name="users",
            table=DirectTrinoTable(
                name="users",
                fields={
                    "id": IntegerDatabaseField(name="id", nullable=False),
                    "user_id": StringDatabaseField(name="user_id", nullable=False),
                    "uuid": UUIDDatabaseField(name="uuid", nullable=False),
                    "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
                    "properties": StringJSONDatabaseField(name="properties", nullable=False),
                },
                external_data_source_id="source-id",
                trino_catalog="ducklake",
                trino_schema="analytics",
                trino_table_name="users",
                has_complete_columns=True,
            ),
        )
    )
    return HogQLContext(
        database=database,
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )


def test_star_projection_preserves_logical_name_for_physical_column_alias() -> None:
    database = Database(include_posthog_tables=False)
    database.tables.add_child(
        TableNode(
            name="subscriptions",
            table=DirectTrinoTable(
                name="subscriptions",
                fields={
                    "customer": StringDatabaseField(name="customer"),
                    "customer_id": StringDatabaseField(name="customer"),
                    "created": IntegerDatabaseField(name="created"),
                    "created_at": ExpressionField(name="created_at", expr=parse_expr("toDateTime(created)")),
                },
                external_data_source_id="source-id",
                trino_catalog="ducklake",
                trino_schema="billing",
                trino_table_name="subscriptions",
                has_complete_columns=True,
            ),
        )
    )
    context = HogQLContext(
        database=database,
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT customer_id FROM (SELECT * FROM subscriptions)"),
        context,
        "trino",
    )

    assert sql.startswith('SELECT "customer_id" FROM (SELECT "subscriptions"."customer", ')
    assert '"subscriptions"."customer" AS "customer_id"' in sql
    assert 'AS "created_at" FROM "ducklake"."billing"."subscriptions"' in sql

    window_sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT customer_id AS customer_id, "
            "row_number() OVER (PARTITION BY customer_id ORDER BY customer_id) AS row_number FROM subscriptions"
        ),
        context,
        "trino",
    )
    assert 'PARTITION BY "subscriptions"."customer" ORDER BY "subscriptions"."customer" ASC' in window_sql


def test_prints_resolved_query_with_explicit_trino_locator_and_bound_value() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT user_id, toDate(created_at) FROM users WHERE user_id = 'person-1'"),
        context,
        "trino",
    )

    assert sql == (
        'SELECT "users"."user_id", CAST("users"."created_at" AS DATE) '
        'FROM "ducklake"."analytics"."users" AS "users" WHERE ("users"."user_id" = %(hogql_val_0)s)'
    )
    assert context.values == {"hogql_val_0": "person-1"}


def test_prints_expanded_saved_query_after_detaching_from_database() -> None:
    context = _context_with_trino_table()
    assert context.database is not None
    context.database.tables.add_child(
        TableNode(
            name="accounts",
            table=SavedQuery(
                id="accounts",
                name="accounts",
                query="SELECT user_id AS account_id FROM users",
                fields={"account_id": StringDatabaseField(name="account_id")},
            ),
        )
    )

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT account_id FROM accounts"),
        context,
        "trino",
    )

    assert sql == (
        'SELECT "accounts"."account_id" FROM '
        '(SELECT "users"."user_id" AS "account_id" FROM "ducklake"."analytics"."users" AS "users") AS "accounts"'
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT user_id FROM users WHERE user_id = 'person-1'",
        "SELECT properties.color, count() FROM users GROUP BY properties.color",
        "SELECT user_id FROM users ORDER BY created_at DESC LIMIT 2 BY user_id",
        "WITH seed AS (SELECT 7 AS n) SELECT n FROM seed UNION ALL SELECT n FROM seed",
        "SELECT user_id FROM users WHERE user_id IN ['violet', 'amber']",
    ],
)
def test_prepared_trino_transpiler_does_not_rebuild_the_schema_database(
    query: str, snapshot: SnapshotAssertion
) -> None:
    preparation_context = _context_with_trino_table()
    prepared = prepare_ast_for_printing(parse_select(query), preparation_context, "trino")
    assert prepared is not None
    assert preparation_context.database is not None

    transpiler_input = TrinoTranspilerInput(
        node=prepared,
        values=tuple(preparation_context.values.items()),
        table_locators=preparation_context.trino_table_locators,
        persons_on_events_mode=preparation_context.modifiers.personsOnEventsMode,
        convert_to_project_timezone=preparation_context.modifiers.convertToProjectTimezone,
        limit_top_select=preparation_context.limit_top_select,
        limit_context=preparation_context.limit_context,
        timezone=preparation_context.database.get_timezone(),
        week_start_day=preparation_context.database.get_week_start_day(),
    )

    with mock.patch(
        "posthog.hogql.database.database.Database.create_for",
        side_effect=AssertionError("the prepared transpiler must not build a database"),
    ):
        transpiled = transpile_prepared_hogql_to_trino(transpiler_input)

    assert (transpiled.sql, transpiled.values) == snapshot


def test_prints_trino_lambda_syntax() -> None:
    context = HogQLContext()
    node = ast.Lambda(args=["value"], expr=ast.Field(chain=["value"], type=ast.LambdaArgumentType(name="value")))

    assert print_prepared_ast(node, context, "trino") == '"value" -> "value"'


def test_uses_trino_arbitrary_value_aggregate_for_any_variants() -> None:
    context = HogQLContext()

    assert print_prepared_ast(ast.Call(name="any", args=[ast.Constant(value=1)]), context, "trino") == "arbitrary(1)"
    assert (
        print_prepared_ast(ast.Call(name="anyLast", args=[ast.Constant(value=1)]), context, "trino") == "arbitrary(1)"
    )


def test_rejects_table_without_trino_locator() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
        use_new_events_schema=False,
        apply_events_retention_floor=False,
    )

    with pytest.raises(QueryError, match="TRINO_TABLE_LOCATOR_MISSING"):
        prepare_and_print_ast(parse_select("SELECT event FROM events"), context, "trino")


def test_normalizes_prewhere_before_validation() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT user_id FROM users PREWHERE user_id != 'blocked' WHERE user_id != 'deleted'"),
        context,
        "trino",
    )

    assert "PREWHERE" not in sql
    assert sql.count('"users"."user_id" !=') == 2


def test_lowers_distinct_limit_by_after_distinct_projection() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT DISTINCT user_id FROM users ORDER BY user_id LIMIT 1 BY user_id"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'SELECT DISTINCT "users"."user_id" AS "user_id"' in sql
    assert 'row_number() OVER (PARTITION BY "__hogql_trino_distinct_0"."user_id"' in sql
    assert 'WHERE ("__hogql_trino_source_1"."__hogql_limit_by_row_1" <= 1)' in sql


def test_ignores_clickhouse_cte_materialization_hint() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("WITH chosen AS MATERIALIZED (SELECT user_id FROM users) SELECT user_id FROM chosen"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'WITH "chosen" AS (SELECT "users"."user_id" FROM "ducklake"."analytics"."users" AS "users")' in sql
    assert "MATERIALIZED" not in sql


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "intDiv(toInt(user_id), 1000)",
            '(CAST(TRY_CAST("users"."user_id" AS BIGINT) AS BIGINT) / CAST(1000 AS BIGINT))',
        ),
        ("arrayZip([1, 2], [3, 4])", "zip(ARRAY[1, 2], ARRAY[3, 4])"),
        (
            "arrayZip(groupArray(user_id), groupArray(created_at))",
            'IF(cardinality(array_agg("users"."user_id")) = cardinality(array_agg("users"."created_at")), zip(',
        ),
        ("extractURLParameter(user_id, 'ref')", "coalesce(substr(element_at(filter(split(IF(strpos("),
        ("extractAllGroups(user_id, '([a-z]+)')", "-> ARRAY[coalesce(__hogql_group, '')])"),
        (
            "extractAllGroups(user_id, '([a-z]+)=([0-9]+)')",
            "-> ARRAY[coalesce(__hogql_match[1], ''), coalesce(__hogql_match[2], '')])",
        ),
        (
            "replaceRegexpOne(user_id, '([a-z]+)', 'x')",
            "__hogql_match -> __hogql_match[1] || %(hogql_val_0)s || __hogql_match[4]",
        ),
        (
            "roundBankers(sum(length(user_id)), -1)",
            'transform(ARRAY[sum(length("users"."user_id"))], __hogql_round_value ->',
        ),
        ("median(length(user_id))", 'approx_percentile(length("users"."user_id"), 0.5)'),
        (
            "medianIf(length(user_id), length(user_id) > 1)",
            'approx_percentile(length("users"."user_id"), 0.5) FILTER (WHERE',
        ),
        ("arrayMap(value -> value + 1, [1, 2])", 'transform(ARRAY[1, 2], "value" -> ("value" + 1))'),
        (
            "arrayMap((left, right) -> left + right, [1, 2], [3, 4])",
            'zip_with(ARRAY[1, 2], ARRAY[3, 4], ("left", "right") -> ("left" + "right"))',
        ),
        ("arrayFilter(value -> value > 1, [1, 2])", 'filter(ARRAY[1, 2], "value" -> ("value" > 1))'),
        ("arrayFold((state, value) -> state + value, [1, 2], 0)", "reduce(ARRAY[1, 2], 0,"),
        ("arrayReverseSort(value -> value, [1, 2])", "reverse(transform(array_sort("),
        ("arrayElement([1, 2], 1)", "element_at(ARRAY[1, 2], 1)"),
        ("indexOf([1, 2], 2)", "array_position(ARRAY[1, 2], 2)"),
        ("leftPad(user_id, 4, '0')", 'lpad("users"."user_id", 4,'),
        ("right(user_id, 2)", 'substr("users"."user_id", -(2))'),
        ("upperUTF8(user_id)", 'upper("users"."user_id")'),
        ("fromUnixTimestamp64Milli(1000)", "from_unixtime((CAST(1000 AS DOUBLE) / 1000e0))"),
        ("TRUNC(1.234, 2)", "truncate(1.234, 2)"),
        ("hasAny([1, 2], [2, 3])", "(cardinality(array_intersect(ARRAY[1, 2], ARRAY[2, 3])) > 0)"),
        (
            "range(2, 5)",
            'filter(sequence(2, greatest((5) - 1, 2)), "__hogql_range_value" -> ("__hogql_range_value" < 5))',
        ),
        ("tuple(1, 2).1", "(ROW(1, 2))[1]"),
        ("extract(user_id, 'id-(.*)')", 'regexp_extract("users"."user_id", %(hogql_val_0)s, 1)'),
        ("JSON_VALUE(user_id, '$.key')", 'json_value("users"."user_id", \'lax $.key\')'),
        (
            "quantileIf(0.9)(length(user_id), user_id != '')",
            'approx_percentile(length("users"."user_id"), 0.9) FILTER',
        ),
        ("argMax(user_id, created_at)", 'max_by("users"."user_id", "users"."created_at")'),
        ("toIntervalMonth(3)", "(CAST(3 AS BIGINT) * INTERVAL '1' MONTH)"),
        ("toInt(toDate('2022-01-01'))", "date_diff('day', DATE '1970-01-01', CAST("),
        ("toInt(created_at)", 'CAST(to_unixtime("users"."created_at") AS BIGINT)'),
        ("arrayCount(x -> x > 1, [1, 2, 3])", 'cardinality(filter(ARRAY[1, 2, 3], "x" -> ("x" > 1)))'),
        (
            "countEqual([1, 2, 1], 1)",
            "element_at(transform(ARRAY[ROW(ARRAY[1, 2, 1], 1)], __hogql_args -> cardinality(filter(",
        ),
        (
            "countEqual(groupArray(user_id), any(user_id))",
            'ARRAY[ROW(array_agg("users"."user_id"), arbitrary("users"."user_id"))]',
        ),
        ("coalesce(properties.enabled, false) = 0", "CAST(coalesce(CAST(json_extract_scalar("),
        ("countDistinctIf(user_id, user_id != '')", 'count(DISTINCT "users"."user_id") FILTER (WHERE'),
        ("multiSearchAnyCaseInsensitive(user_id, ['a']) = 1", "CAST(any_match("),
        ("toFloat64OrNull(user_id)", 'TRY_CAST("users"."user_id" AS DOUBLE)'),
        ("accurateCastOrNull(user_id, 'Int64')", 'TRY_CAST("users"."user_id" AS BIGINT)'),
        ("DATE(created_at)", 'CAST("users"."created_at" AS DATE)'),
        ("domain(user_id)", "coalesce(TRY(url_extract_host(CAST("),
        ("multiplyDecimal(1, 2)", "CAST((1 * 2) AS DECIMAL(38, 0))"),
        ("quantileExact(0.9)(length(user_id))", "array_sort(filter(array_agg(length("),
        ("ngramDistance(user_id, 'abc')", "MAP(VARBINARY, BIGINT)"),
        ("formatReadableTimeDelta(3661)", "'hour', 'hours'"),
        (
            "multiSearchAnyCaseInsensitive(user_id, ['Ab'])",
            "any_match(ARRAY[%(hogql_val_0)s], __hogql_needle -> strpos(lower(",
        ),
        (
            "replaceOne(user_id, 'a', 'b')",
            'CASE WHEN length(%(hogql_val_0)s) = 0 OR strpos("users"."user_id", %(hogql_val_0)s) = 0',
        ),
        ("floor(1.234, 2)", "(floor(1.234 * power(10, 2)) / power(10, 2))"),
        ("ceil(-1.234, 2)", "(ceil(-1.234 * power(10, 2)) / power(10, 2))"),
        ("md5(user_id AS TEXT)", 'to_hex(md5(to_utf8(CAST("users"."user_id" AS VARCHAR))))'),
        ("splitByString(',', user_id, 2)", 'ELSE slice(split("users"."user_id", %(hogql_val_0)s), 1, 2) END'),
        ("arraySlice([1, 2, 3], -2, -1)", "slice(ARRAY[1, 2, 3], greatest(1, IF(-2 < 0,"),
        ("arraySort(x -> -x, [1, 3, 2])", 'transform(array_sort(transform(ARRAY[1, 3, 2], "x" -> ROW('),
        ("toStartOfInterval(created_at, INTERVAL 10 MINUTE)", " / 600e0) AS BIGINT) * 600"),
        ("parseDateTimeBestEffort(user_id)", 'CAST(at_timezone(coalesce(IF(regexp_like("users"."user_id",'),
        (
            "dateDiff('day', user_id, created_at)",
            'date_diff(%(hogql_val_0)s, CAST("users"."user_id" AS TIMESTAMP), "users"."created_at")',
        ),
        ("CASE user_id WHEN 'a' THEN 1 ELSE 2 END", 'CASE "users"."user_id" WHEN %(hogql_val_0)s THEN 1 ELSE 2 END'),
        ("if(2, 3, 4)", "CASE WHEN CAST(2 AS BOOLEAN) THEN 3 ELSE 4 END"),
        ("NOT properties.enabled", "NOT CAST(json_extract_scalar("),
        ("log(2)", "ln(2)"),
        ("toInt(user_id)", 'TRY_CAST("users"."user_id" AS BIGINT)'),
        ("countDistinctIf(user_id, 1)", "FILTER (WHERE CAST(1 AS BOOLEAN))"),
        ("coalesce(properties.enabled, false)", "coalesce(CAST(json_extract_scalar("),
        ("positionCaseInsensitive(user_id, 'ab')", 'strpos(lower("users"."user_id"), lower('),
        ("lowerUTF8(user_id)", 'lower("users"."user_id")'),
        ("arrayEnumerate([10, 20])", "sequence(1, cardinality(ARRAY[10, 20]))"),
        ("arrayExists(x -> x > 1, [1, 2])", 'any_match(ARRAY[1, 2], "x" -> ("x" > 1))'),
        ("cutToFirstSignificantSubdomain(user_id)", "array_join(slice(filter(split(lower(trim(TRAILING '.' FROM"),
        ("mapFromArrays([user_id], [1])", "map(__hogql_args[1], __hogql_args[2])"),
        ("equals(length(user_id), '3')", 'length("users"."user_id") = CAST('),
        ("sum(user_id)", 'sum(TRY_CAST("users"."user_id" AS DOUBLE))'),
        ("lengthUTF8(user_id)", 'length("users"."user_id")'),
        ("hex(user_id)", 'to_hex(to_utf8(CAST("users"."user_id" AS VARCHAR)))'),
        ("toUUIDOrDefault(user_id, user_id)", 'coalesce(TRY_CAST("users"."user_id" AS UUID)'),
        ("toFloat(created_at)", 'to_unixtime("users"."created_at")'),
        ("coalesce(user_id, 1)", 'coalesce("users"."user_id", CAST(1 AS VARCHAR))'),
        ("toString([1, 2])", "json_format(CAST(ARRAY[1, 2] AS JSON))"),
        ("created_at = 0", '"users"."created_at" = from_unixtime(CAST(0 AS DOUBLE))'),
        ("_toUInt64(user_id)", 'CAST("users"."user_id" AS BIGINT)'),
        ("_toUInt64(created_at)", 'CAST(to_unixtime("users"."created_at") AS BIGINT)'),
        ("encodeURLComponent(user_id)", 'url_encode("users"."user_id")'),
        ("in(user_id, tuple('one'))", '("users"."user_id" IN (%(hogql_val_0)s))'),
        ("max2(1, 2)", "greatest(1, 2)"),
        ("min2(1, 2)", "least(1, 2)"),
        ("positiveModulo(-3, 2)", "mod(mod(-3, 2) + 2, 2)"),
        ("arrayPopFront([1, 2])", "slice(ARRAY[1, 2], 2, greatest(cardinality(ARRAY[1, 2]) - 1, 0))"),
        ("arrayPopBack([1, 2])", "slice(ARRAY[1, 2], 1, greatest(cardinality(ARRAY[1, 2]) - 1, 0))"),
        ("arrayPushFront([1], 2)", "concat(ARRAY[2], ARRAY[1])"),
        ("arrayPushBack([1], 2)", "concat(ARRAY[1], ARRAY[2])"),
        ("arrayDifference([1, 3])", "ARRAY[1, 3][__hogql_index] - ARRAY[1, 3][__hogql_index - 1]"),
        ("arrayUniq([1, 1, 2])", "cardinality(array_distinct(ARRAY[1, 1, 2]))"),
        ("arrayWithConstant(2, 7)", "repeat(7, CAST(2 AS BIGINT))"),
        ("base64Encode(user_id)", 'to_base64(to_utf8("users"."user_id"))'),
        ("base64Decode(user_id)", 'from_utf8(from_base64("users"."user_id"))'),
        ("ascii(user_id)", 'from_base(to_hex(substr(to_utf8("users"."user_id"), 1, 1)), 16)'),
        ("left(user_id, 2)", 'substr("users"."user_id", 1, 2)'),
        ("mapContains(mapFromArrays(['a'], [1]), 'a')", "contains(map_keys(map(ARRAY["),
        ("json_agg(user_id)", 'json_format(CAST(array_agg("users"."user_id") AS JSON))'),
        ("string_agg(user_id, ',')", 'array_join(array_agg("users"."user_id"),'),
        ("every(length(user_id) > 0)", "bool_and(CAST((length("),
        ("stddevPop(length(user_id))", 'stddev_pop(length("users"."user_id"))'),
        ("varSamp(length(user_id))", 'var_samp(length("users"."user_id"))'),
        ("monthName(created_at)", 'date_format("users"."created_at", \'%M\')'),
        ("toUnixTimestamp64Milli(created_at)", 'CAST(to_unixtime("users"."created_at") * 1000 AS BIGINT)'),
        ("isValidJSON(user_id)", 'TRY(json_parse(CAST("users"."user_id" AS VARCHAR))) IS NOT NULL'),
        ("exp2(3)", "power(2, 3)"),
        ("log1p(3)", "ln(1 + 3)"),
        ("bitAnd(3, 1)", "bitwise_and(3, 1)"),
        ("arrayAvg([1, 2, 3])", "reduce(ARRAY[1, 2, 3], DOUBLE '0'"),
        ("arrayCompact([1, 1, 2])", "element_at(__hogql_result, -1) IS DISTINCT FROM __hogql_value"),
        (
            "arrayEnumerateDense([10, 20, 10])",
            "array_position(transform(array_distinct(slice(ARRAY[10, 20, 10]",
        ),
        (
            "arrayEnumerateUniq([10, 20, 10], [1, 1, 1])",
            "cardinality(filter(slice(zip(ARRAY[10, 20, 10], ARRAY[1, 1, 1])",
        ),
        ("arrayFirstIndex(x -> x > 1, [1, 2])", 'coalesce(array_position(transform(ARRAY[1, 2], "x" ->'),
        (
            "arrayLastIndex(x -> x > 1, [1, 2])",
            'IF(array_position(reverse(transform(ARRAY[1, 2], "x" ->',
        ),
        ("arrayRotateLeft([1, 2, 3], 1)", "concat(slice(ARRAY[1, 2, 3]"),
        ("arrayRotateRight([1, 2, 3], 1)", "mod(mod(-(1), cardinality(ARRAY[1, 2, 3]))"),
        ("hasSubstr([1, 2, 3], [2, 3])", "contains_sequence(ARRAY[1, 2, 3], ARRAY[2, 3])"),
        (
            "appendTrailingCharIfAbsent(user_id, '/')",
            "fail('appendTrailingCharIfAbsent expects one character')",
        ),
        ("countMatches(user_id, 'a')", 'cardinality(regexp_extract_all("users"."user_id"'),
        ("countSubstrings(user_id, 'a')", 'length(replace("users"."user_id"'),
        ("splitByRegexp('-', user_id)", 'regexp_split("users"."user_id"'),
        ("mapContainsKeyLike(mapFromArrays(['a'], [1]), 'a%')", "cardinality(map_filter(map(ARRAY["),
        ("bitTest(4, 2)", "bitwise_and(4, bitwise_left_shift(BIGINT '1', 2)) <> 0"),
        ("bitTestAll(6, 1, 2)", "bitwise_and(6, bitwise_left_shift(BIGINT '1', 1)) <> 0 AND"),
        ("bitShiftRight(-8, 1)", "bitwise_right_shift_arithmetic(-8, 1)"),
        ("bitHammingDistance(5, 1)", "bit_count(bitwise_xor(5, 1), 64)"),
        ("L2Distance([1, 2], [3, 4])", "euclidean_distance(ARRAY[1, 2], ARRAY[3, 4])"),
        ("port('https://example.com', 443)", "coalesce(url_extract_port("),
        ("age('day', created_at, created_at)", "date_diff("),
        ("arrayResize([1, 2], -3, 0)", "concat(repeat(0, greatest(-("),
        ("groupBitAnd(length(user_id))", 'bitwise_and_agg(length("users"."user_id"))'),
        ("domainWithoutWWW('https://www.example.com')", "regexp_replace(coalesce(url_extract_host("),
        ("topLevelDomain('https://www.example.com')", "element_at(split(coalesce(url_extract_host("),
        ("L1Distance([1, 2], [3, 5])", "reduce(zip_with(ARRAY[1, 2], ARRAY[3, 5]"),
        ("L2Norm([3, 4])", "sqrt(dot_product(ARRAY[3, 4], ARRAY[3, 4]))"),
        ("toModifiedJulianDay(created_at)", "date_diff('day', DATE '1858-11-17'"),
        ("fromModifiedJulianDay(60000)", "date_add('day', CAST(60000 AS BIGINT), DATE '1858-11-17')"),
    ],
)
def test_prints_core_trino_expression_mappings(expression: str, expected: str) -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(parse_select(f"SELECT {expression} FROM users"), context, "trino")

    assert expected in sql


def test_drops_clickhouse_global_distribution_modifiers() -> None:
    membership_query = parse_select("SELECT user_id FROM users WHERE user_id IN ['a']")
    assert isinstance(membership_query.where, ast.CompareOperation)
    membership_query.where.op = ast.CompareOperationOp.GlobalIn
    membership_sql, _ = prepare_and_print_ast(
        membership_query,
        _context_with_trino_table(),
        "trino",
    )
    assert "GLOBAL" not in membership_sql
    assert '"users"."user_id" IN (%(hogql_val_0)s)' in membership_sql

    query = parse_select("SELECT users.user_id FROM users LEFT JOIN users AS other ON users.user_id = other.user_id")
    assert isinstance(query.select_from, ast.JoinExpr)
    assert query.select_from.next_join is not None
    query.select_from.next_join.join_type = "GLOBAL LEFT JOIN"
    join_sql, _ = prepare_and_print_ast(query, _context_with_trino_table(), "trino")
    assert "GLOBAL" not in join_sql
    assert "LEFT JOIN" in join_sql


def test_tracks_every_registered_function_without_a_trino_mapping(snapshot: SnapshotAssertion) -> None:
    supported = {
        *TRINO_FUNCTION_HANDLERS_LOWER,
        *TRINO_FUNCTION_RENAMES_LOWER,
        *TRINO_PASSTHROUGH_FUNCTIONS,
        *_SPECIAL_CALLS,
    }
    registries = {
        "scalar": HOGQL_CLICKHOUSE_FUNCTIONS,
        "aggregate": HOGQL_AGGREGATIONS,
        "posthog": HOGQL_POSTHOG_FUNCTIONS,
    }
    unsupported = {
        group: sorted(name for name in registry if name.lower() not in supported)
        for group, registry in registries.items()
    }

    assert unsupported == snapshot


@pytest.mark.parametrize(
    "expression, feature_code",
    [
        ("intDiv(1.5, 2)", "TRINO_INT_DIV_TYPE_UNSUPPORTED"),
        ("roundBankers(1, length(user_id))", "TRINO_ROUND_BANKERS_PRECISION_UNSUPPORTED"),
        ("roundBankers(1, 19)", "TRINO_ROUND_BANKERS_PRECISION_UNSUPPORTED"),
        ("arrayZip([1], [2, 3])", "TRINO_FUNCTION_ARGUMENTS_UNSUPPORTED"),
        ("arrayZip([1], [2], [3], [4], [5], [6])", "TRINO_ARRAY_ZIP_DYNAMIC_UNSUPPORTED"),
        ("extractAllGroups(user_id, user_id)", "TRINO_REGEX_CONSTANT_REQUIRED"),
        ("extractAllGroups(user_id, '(a)(b)(c)(d)(e)(f)')", "TRINO_REGEX_GROUPS_UNSUPPORTED"),
        ("replaceRegexpOne(user_id, 'a', user_id)", "TRINO_REGEX_CONSTANT_REQUIRED"),
        ("cityHash64(user_id)", "TRINO_FUNCTION_UNSUPPORTED"),
    ],
)
def test_rejects_unsupported_printer_function_variants(expression: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(parse_select(f"SELECT {expression} FROM users"), _context_with_trino_table(), "trino")

    assert error.value.feature_code == feature_code


def test_first_regex_replacement_preserves_capture_indices_and_literal_dollars() -> None:
    context = _context_with_trino_table()
    sql, _ = prepare_and_print_ast(
        parse_select(r"SELECT replaceRegexpOne(user_id, '([a-z])([0-9])', '\\2$\\1') FROM users"), context, "trino"
    )

    assert r"(?s)\A(.*?)(([a-z])([0-9]))(.*)\z" in context.values.values()
    assert "$" in context.values.values()
    assert "coalesce(__hogql_match[4], '') || %(hogql_val_0)s || coalesce(__hogql_match[3], '')" in sql
    assert "__hogql_match[5]" in sql


def test_first_regex_replacement_preserves_inline_flags() -> None:
    context = _context_with_trino_table()
    prepare_and_print_ast(parse_select("SELECT replaceRegexpOne(user_id, '(?i)a', 'b') FROM users"), context, "trino")

    assert r"(?s)\A(.*?)((?i)a)(.*)\z" in context.values.values()


@pytest.mark.parametrize(
    "query, expected",
    [
        ("SELECT (user_id AS inner_name) AS result FROM users", 'AS "result"'),
        ("SELECT user_id FROM users GROUP BY user_id HAVING count() > 0 AS keep", "HAVING (count(*) > 0)"),
    ],
)
def test_omits_expression_aliases_outside_select_projections(query: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino")
    assert expected in sql
    assert 'AS "inner_name"' not in sql
    assert 'AS "keep"' not in sql


def test_coerces_strict_trino_types_after_property_lowering() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT properties.duration / 1000, sum(properties.amount), properties.failed = true, "
            "created_at >= '2026-04-01' FROM users"
        ),
        context,
        "trino",
    )

    assert 'CAST(json_extract_scalar("users"."properties", %(hogql_val_0)s) AS DOUBLE) / CAST(1000 AS DOUBLE)' in sql
    assert 'sum(CAST(json_extract_scalar("users"."properties", %(hogql_val_1)s) AS DOUBLE))' in sql
    assert 'CAST(json_extract_scalar("users"."properties", %(hogql_val_2)s) AS BOOLEAN) = true' in sql
    assert '"users"."created_at" >= CAST(%(hogql_val_3)s AS TIMESTAMP)' in sql


def test_prints_iso_datetime_and_heterogeneous_concat_for_trino() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT toDateTime('2025-06-03T12:00:34.000Z'), concat('ticket-', length(user_id)) FROM users"),
        context,
        "trino",
    )

    assert "CAST(from_iso8601_timestamp(%(hogql_val_0)s) AS TIMESTAMP)" in sql
    assert 'concat(CAST(%(hogql_val_1)s AS VARCHAR), CAST(length("users"."user_id") AS VARCHAR))' in sql


def test_preserves_date_return_type_for_trino_date_truncation() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT toStartOfMonth(created_at), toStartOfDay(created_at) FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'CAST(date_trunc(\'month\', "users"."created_at") AS DATE)' in sql
    assert 'date_trunc(\'day\', "users"."created_at")' in sql
    assert 'CAST(date_trunc(\'day\', "users"."created_at") AS DATE)' not in sql


def test_uses_trino_array_cardinality_and_lax_json_paths() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT length(arrayDistinct([1, 1])), JSON_VALUE(properties, '$.items'), "
            "JSON_VALUE(properties, 'strict $.items') FROM users"
        ),
        context,
        "trino",
    )

    assert "cardinality(array_distinct(ARRAY[1, 1]))" in sql
    assert 'json_value("users"."properties", \'lax $.items\')' in sql
    assert 'json_value("users"."properties", \'strict $.items\')' in sql


def test_preserves_clickhouse_json_array_indexing() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT JSONExtractString(user_id, 'key.with.dot', 2), "
            "JSONExtractRaw(properties, length(user_id)), "
            "JSONExtract(properties, 1, 'Map(String, String)'), "
            "JSONHas(properties, 1), JSONLength(properties, 1), "
            "JSONExtractKeys(properties, 1) FROM users"
        ),
        context,
        "trino",
    )

    assert "element_at(CAST(json_parse(CAST(json_extract(" in sql
    assert "AS ARRAY(JSON)), 2)" in sql
    assert 'AS ARRAY(JSON)), CAST(length("users"."user_id") AS INTEGER))' in sql
    assert sql.count("element_at(") == 6
    assert context.values == {"hogql_val_0": '$["key.with.dot"]'}


def test_lowers_event_property_backed_fields_to_the_physical_json_column() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        trino_table_locators={"events": ("tenant", "posthog", "events")},
    )

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT events.`$session_id`, events.`$window_id`, events.`$group_0` FROM events"),
        context,
        "trino",
    )

    assert 'json_extract_scalar("tenant"."posthog"."events"."properties", %(hogql_val_0)s)' in sql
    assert 'json_extract_scalar("tenant"."posthog"."events"."properties", %(hogql_val_1)s)' in sql
    assert 'json_extract_scalar("tenant"."posthog"."events"."properties", %(hogql_val_2)s)' in sql
    assert context.values == {
        "hogql_val_0": '$["$session_id"]',
        "hogql_val_1": '$["$window_id"]',
        "hogql_val_2": '$["$group_0"]',
    }


def test_lowers_event_element_materializations_to_the_physical_chain() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        trino_table_locators={"events": ("tenant", "posthog", "events")},
    )

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT elements_chain_href, elements_chain_ids FROM events"),
        context,
        "trino",
    )

    assert 'regexp_extract("tenant"."posthog"."events"."elements_chain", %(hogql_val_0)s, 1)' in sql
    assert 'array_distinct(regexp_extract_all("tenant"."posthog"."events"."elements_chain"' in sql


@pytest.mark.parametrize(
    "expression, group_by, order_by, expected_order, expected_values",
    [
        ("user_id", "account_id", "total", "2 ASC", []),
        (
            "concat(user_id, 'suffix')",
            "concat(user_id, 'suffix')",
            "account_id DESC",
            "1 DESC",
            ["suffix"],
        ),
        ("properties.color", "account_id", "account_id", "1 ASC", ['$["color"]']),
        ("0", "account_id", "account_id", "1 ASC", []),
        ("user_id", "account_id", "2", "2 ASC", []),
        (
            "user_id",
            "account_id",
            "concat(account_id, 'suffix')",
            'concat(CAST("users"."user_id" AS VARCHAR), CAST(? AS VARCHAR)) ASC',
            ["suffix"],
        ),
    ],
)
def test_lowers_clickhouse_select_alias_references_to_expressions(
    expression: str, group_by: str, order_by: str, expected_order: str, expected_values: list[str]
) -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            f"SELECT {expression} AS account_id, count() AS total FROM users "
            f"GROUP BY {group_by} HAVING total > 0 ORDER BY {order_by}"
        ),
        context,
        "trino",
    )

    assert "GROUP BY 1" in sql
    assert "HAVING (count(*) > 0)" in sql
    sql, values = convert_pyformat_placeholders(sql, context.values)
    assert sql.endswith(f"ORDER BY {expected_order}")
    assert values == expected_values


def test_inlines_scalar_ctes_for_trino() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("WITH '2025-01-01' AS cutoff SELECT user_id FROM users WHERE created_at >= toDateTime(cutoff)"),
        _context_with_trino_table(),
        "trino",
    )

    assert "WITH" not in sql
    assert '"users"."created_at" >= CAST(%(hogql_val_0)s AS TIMESTAMP)' in sql


def test_lowers_dynamic_numbers_with_a_bounded_cardinality() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT number FROM numbers(dateDiff('day', toDate('2025-01-01'), today()))"),
        _context_with_trino_table(),
        "trino",
    )

    assert "least(greatest(" in sql
    assert "10000000" in sql


@pytest.mark.parametrize(
    "expression, expected",
    [
        (
            "''",
            "(%(hogql_val_0)s IS NULL OR %(hogql_val_0)s = ''), "
            "(%(hogql_val_1)s IS NOT NULL AND %(hogql_val_1)s <> '')",
        ),
        ("[]", "(ARRAY[] IS NULL OR cardinality(ARRAY[]) = 0), (ARRAY[] IS NOT NULL AND cardinality(ARRAY[]) > 0)"),
        (
            "[1]",
            "(ARRAY[1] IS NULL OR cardinality(ARRAY[1]) = 0), (ARRAY[1] IS NOT NULL AND cardinality(ARRAY[1]) > 0)",
        ),
        (
            "mapFromArrays([], [])",
            "(map(ARRAY[], ARRAY[]) IS NULL OR cardinality(map(ARRAY[], ARRAY[])) = 0), "
            "(map(ARRAY[], ARRAY[]) IS NOT NULL AND cardinality(map(ARRAY[], ARRAY[])) > 0)",
        ),
        (
            "mapFromArrays([1], [2])",
            "(map(ARRAY[1], ARRAY[2]) IS NULL OR cardinality(map(ARRAY[1], ARRAY[2])) = 0), "
            "(map(ARRAY[1], ARRAY[2]) IS NOT NULL AND cardinality(map(ARRAY[1], ARRAY[2])) > 0)",
        ),
    ],
)
def test_prints_empty_according_to_resolved_argument_type(expression: str, expected: str) -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT empty({expression}), notEmpty({expression})"), context, "trino"
    )

    assert sql == f"SELECT {expected}"


@pytest.mark.parametrize("value, expected_empty", [("", True), ("hello", False), (None, True)])
def test_empty_string_predicates_return_expected_results(value: str | None, expected_empty: bool) -> None:
    context = HogQLContext()
    argument = ast.Constant(value=value, type=ast.StringType(nullable=True))
    empty_sql = print_prepared_ast(ast.Call(name="empty", args=[argument]), context, "trino")
    not_empty_sql = print_prepared_ast(ast.Call(name="notEmpty", args=[argument]), context, "trino")
    sql, values = convert_pyformat_placeholders(f"SELECT {empty_sql}, {not_empty_sql}", context.values)

    with closing(sqlite3.connect(":memory:")) as connection:
        assert connection.execute(sql, values).fetchone() == (expected_empty, not expected_empty)


def test_rejects_empty_for_unsupported_types_with_stable_error() -> None:
    context = _context_with_trino_table()

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(parse_select("SELECT notEmpty(1)"), context, "trino")

    assert error.value.feature_code == "TRINO_EMPTY_ARGUMENT_TYPE_UNSUPPORTED"


def test_prints_empty_for_lowered_json_property_after_second_resolution() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT notEmpty(properties.task_run_id) FROM users"),
        context,
        "trino",
    )

    assert 'json_extract_scalar("users"."properties", %(hogql_val_0)s) <> \'\'' in sql
    assert context.values == {"hogql_val_0": '$["task_run_id"]'}


def test_lowers_nested_json_keys_and_values_raw() -> None:
    context = _context_with_trino_table()
    sql, _ = prepare_and_print_ast(parse_select("SELECT JSONExtractKeysAndValuesRaw('{}', 'teams')"), context, "trino")

    assert "map_entries(CAST(json_extract(" in sql
    assert context.values == {"hogql_val_0": "{}", "hogql_val_1": '$["teams"]'}


def test_lowers_currency_conversion_with_the_trino_exchange_rate_table() -> None:
    context = _context_with_trino_table()
    context.trino_table_locators = {
        **context.trino_table_locators,
        "exchange_rate": ("ducklake", "posthog", "exchange_rate"),
    }

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT convertCurrency(user_id, 'USD', 100, DATE(created_at)) FROM users"),
        context,
        "trino",
    )

    assert "max_by(CAST(__hogql_from_rate.rate AS DECIMAL(38, 10)), __hogql_from_rate.date)" in sql
    assert 'FROM "ducklake"."posthog"."exchange_rate" AS __hogql_from_rate' in sql
    assert '__hogql_from_rate.date <= CAST(CAST("users"."created_at" AS DATE) AS DATE)' in sql
    assert "NULLIF" in sql


def test_rejects_currency_conversion_without_an_exchange_rate_locator() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT convertCurrency(user_id, 'USD', 100) FROM users"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_EXCHANGE_RATE_TABLE_REQUIRED"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("numbers(3)", "sequence(0, greatest((3) - 1, 0))"),
        ("numbers(4, 2)", "sequence(4, greatest((6) - 1, 4))"),
        ("numbers(0)", "sequence(0, greatest((0) - 1, 0))"),
    ],
)
def test_lowers_numbers_to_bounded_unnest(source: str, expected: str) -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )

    sql, _ = prepare_and_print_ast(parse_select(f"SELECT number FROM {source}"), context, "trino")

    assert f"FROM UNNEST(filter({expected}" in sql
    assert 'AS "numbers" ("number")' in sql


def test_bounds_dynamic_numbers_input() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT number FROM numbers(dateDiff('day', toDate('2025-01-01'), today()))"),
        context,
        "trino",
    )

    assert "least(greatest(" in sql
    assert "10000000" in sql


def test_lowers_single_array_join_to_cross_join_unnest() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT item FROM users ARRAY JOIN [1, 2] AS item"),
        context,
        "trino",
    )

    assert (
        'CROSS JOIN UNNEST(transform(ARRAY[1, 2], "__trino_unnest_0_value" -> ROW("__trino_unnest_0_value"))) '
        'AS "__trino_unnest_0" ("item")'
        in sql
        and 'SELECT "__trino_unnest_0"."item"' in sql
    )


def test_internal_unnest_function_is_not_shadowed_by_a_cte() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("WITH __trino_unnest AS (SELECT 1 AS value) SELECT arrayJoin([1, 2]) AS item"),
        context,
        "trino",
    )

    assert "FROM UNNEST(transform(ARRAY[1, 2]" in sql
    assert 'AS "__trino_array_function_0" ("value_0")' in sql


def test_lowers_multi_array_join_with_equal_cardinality_guard() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT first, second FROM users "
            "ARRAY JOIN splitByChar(',', user_id) AS first, splitByChar(',', user_id) AS second"
        ),
        context,
        "trino",
    )

    assert "CROSS JOIN UNNEST(IF(cardinality(split(" in sql
    assert "= cardinality(split(" in sql
    assert 'AS "__trino_unnest_0" ("first", "second")' in sql


def test_lowers_array_join_function_to_cross_join_unnest() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT arrayJoin([1, 2]) AS item FROM users"),
        context,
        "trino",
    )

    assert 'SELECT "__trino_array_function_0"."value_0" AS "item"' in sql
    assert (
        'CROSS JOIN UNNEST(transform(ARRAY[1, 2], "__trino_array_function_0_value" -> '
        'ROW("__trino_array_function_0_value"))) AS "__trino_array_function_0" ("value_0")' in sql
    )


def test_lowers_select_alias_inside_array_join_function() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT [user_id] AS ids, arrayJoin(ids) AS item FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'UNNEST(transform(ARRAY["users"."user_id"]' in sql
    assert 'UNNEST(transform("ids"' not in sql


def test_lowers_ordered_funnel_aggregation_to_trino_array_processing() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT groupArray(tuple(1, 2, user_id, '', [1, 2])) AS events_array, "
            "arrayJoin(aggregate_funnel_trends(1, 2, 2, 10, 'first_touch', 'ordered', [''], events_array)) "
            "AS funnel_result FROM users"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert "CROSS JOIN UNNEST" in sql
    assert "reduce(zip_with(__hogql_funnel_chain" in sql
    assert "__hogql_funnel_event[1] - __hogql_funnel_entrance[1] <= 10" in sql
    assert "contains(__hogql_funnel_item[1][5], -CAST((__hogql_funnel_state[1] + 1) AS TINYINT))" in sql
    assert "slice(" not in sql


def test_lowers_limit_by_to_row_number_wrapper() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT user_id, created_at FROM users ORDER BY created_at DESC LIMIT 2 BY user_id LIMIT 5"),
        context,
        "trino",
    )

    assert 'row_number() OVER (PARTITION BY "users"."user_id" ORDER BY "users"."created_at" DESC)' in sql
    assert 'WHERE ("__hogql_trino_source_0"."__hogql_limit_by_row_0" <= 2)' in sql
    assert 'ORDER BY "__hogql_trino_source_0"."created_at" DESC LIMIT 5' in sql
    assert "LIMIT 2 BY" not in sql


def test_lowers_qualify_alias_to_outer_filter() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT user_id, row_number() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS position "
            "FROM users QUALIFY position = 1"
        ),
        context,
        "trino",
    )

    assert 'AS "position" FROM "ducklake"."analytics"."users"' in sql
    assert 'WHERE ("__hogql_trino_source_0"."position" = 1)' in sql
    assert "QUALIFY" not in sql


def test_lowers_window_count_distinct_without_unsupported_distinct_window_aggregate() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT countDistinct(user_id) OVER (PARTITION BY created_at) FROM users"),
        context,
        "trino",
    )

    assert "cardinality(array_distinct(filter(array_agg(" in sql
    assert 'OVER (PARTITION BY "users"."created_at")' in sql
    assert "count(DISTINCT" not in sql


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("Array(String)", "ARRAY(VARCHAR)"),
        ("Nullable(Array(UInt64))", "ARRAY(DECIMAL(20, 0))"),
        ("Decimal(18, 2)", "DECIMAL(18,2)"),
        ("DateTime64(6)", "TIMESTAMP(6)"),
        ("FixedString(8)", "CHAR(8)"),
        ("timestamp with time zone", "TIMESTAMP WITH TIME ZONE"),
    ],
)
def test_renders_allowlisted_trino_cast_types(type_name: str, expected: str) -> None:
    query = parse_select("SELECT user_id FROM users")
    assert isinstance(query, ast.SelectQuery)
    query.select[0] = ast.TypeCast(expr=query.select[0], type_name=type_name)

    sql, _ = prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert f" AS {expected})" in sql


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
def test_rejects_invalid_trino_cast_types(type_name: str) -> None:
    query = parse_select("SELECT user_id FROM users")
    assert isinstance(query, ast.SelectQuery)
    query.select[0] = ast.TypeCast(expr=query.select[0], type_name=type_name)

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert error.value.feature_code == "TRINO_CAST_TYPE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("query", "expected_suffix"),
    [
        ("SELECT user_id FROM users LIMIT 10 OFFSET 4", "OFFSET 4 ROWS LIMIT 10"),
        (
            "SELECT user_id FROM users ORDER BY user_id LIMIT 10 WITH TIES",
            "FETCH FIRST 10 ROWS WITH TIES",
        ),
    ],
)
def test_prints_trino_limit_syntax(query: str, expected_suffix: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino")

    assert sql.endswith(expected_suffix)


def test_prints_trino_limit_syntax_after_set_operation() -> None:
    query = parse_select("SELECT user_id FROM users UNION ALL SELECT user_id FROM users")
    assert isinstance(query, ast.SelectSetQuery)
    query.limit = ast.Constant(value=10)
    query.offset = ast.Constant(value=4)

    sql, _ = prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert sql.endswith("OFFSET 4 ROWS LIMIT 10")


def test_aligns_string_and_uuid_set_columns_as_varchar() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT user_id AS value FROM users UNION ALL SELECT uuid AS value FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'CAST("users"."user_id" AS VARCHAR)' in sql
    assert 'CAST("users"."uuid" AS VARCHAR)' in sql


def test_casts_numeric_value_for_string_in_subquery() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT id FROM users WHERE id IN (SELECT user_id FROM users)"),
        _context_with_trino_table(),
        "trino",
    )

    assert 'CAST("users"."id" AS VARCHAR) IN (SELECT "users"."user_id"' in sql


@pytest.mark.parametrize("pretty", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_set_query_ctes_are_visible_to_every_operand(pretty: bool, nested: bool) -> None:
    query = "WITH seed AS (SELECT 7 AS n) SELECT n FROM seed LIMIT 1 UNION ALL SELECT n FROM seed"
    if nested:
        query = f"SELECT n FROM ({query})"

    sql, _ = prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino", pretty=pretty)

    compact = " ".join(sql.split())
    assert 'WITH "seed" AS (SELECT 7 AS "n")' in compact
    assert '(SELECT "seed"."n" FROM "seed" LIMIT 1) UNION ALL (SELECT "seed"."n" FROM "seed")' in compact
    assert compact.count('WITH "seed"') == 1
    if not nested:
        assert compact.startswith("WITH ")


@pytest.mark.parametrize("branch_is_set", [False, True])
@pytest.mark.parametrize("branch_first", [False, True])
def test_set_operand_preserves_branch_local_cte_scope(branch_is_set: bool, branch_first: bool) -> None:
    branch = "WITH seed AS (SELECT 11 AS n) SELECT n FROM seed"
    if branch_is_set:
        branch += " UNION ALL SELECT n FROM seed"
    outer = "WITH seed AS (SELECT 7 AS n) SELECT n FROM seed"
    query = f"({branch}) UNION ALL ({outer})" if branch_first else f"{outer} UNION ALL ({branch})"

    sql, _ = prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino")

    assert 'WITH "seed" AS (SELECT 7 AS "n") ' in sql
    assert 'WITH "seed" AS (SELECT 11 AS "n") ' in sql
    assert "(SELECT * FROM (WITH " in sql


def test_rejects_non_literal_trino_limit() -> None:
    query = parse_select("SELECT user_id FROM users")
    assert isinstance(query, ast.SelectQuery)
    query.limit = ast.Call(name="least", args=[ast.Constant(value=10), ast.Constant(value=20)])

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert error.value.feature_code == "TRINO_ROW_COUNT_NON_LITERAL"


def test_rejects_with_fill_before_printing_invalid_trino_sql() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT user_id FROM users ORDER BY user_id WITH FILL"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_WITH_FILL_UNSUPPORTED"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("user_id ILIKE 'person-%'", 'lower("users"."user_id") LIKE lower(%(hogql_val_0)s)'),
        (
            "uniq(user_id, created_at)",
            'count(DISTINCT ROW("users"."user_id", "users"."created_at"))',
        ),
        ("toDateTime64(created_at, 6)", 'CAST("users"."created_at" AS TIMESTAMP(6))'),
        (
            "dateAdd(toDate('2026-01-01'), toIntervalMonth(1))",
            "(CAST(%(hogql_val_0)s AS DATE) + (CAST(1 AS BIGINT) * INTERVAL '1' MONTH))",
        ),
        ("date_part('year', created_at)", 'EXTRACT(YEAR FROM "users"."created_at")'),
        (
            "JSONExtractKeysAndValues(properties, 'Float64')",
            'map_entries(transform_values(CAST(json_extract("users"."properties", %(hogql_val_0)s) AS MAP(VARCHAR, JSON))',
        ),
        ("['a', 'b'][2:]", "slice(ARRAY[%(hogql_val_0)s, %(hogql_val_1)s], 2, 2147483647)"),
    ],
)
def test_prints_additional_semantics_safe_trino_expressions(expression: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT {expression} FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert expected in sql


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("endsWith(user_id, '1')", 'ends_with("users"."user_id", %(hogql_val_0)s)'),
        ("mapFromArrays(['a'], [1])", "map(ARRAY[%(hogql_val_0)s], ARRAY[1])"),
        (
            "mapUpdate(mapFromArrays(['a'], [1]), mapFromArrays(['a'], [2]))",
            "map_concat(map(ARRAY[%(hogql_val_0)s], ARRAY[1]), map(ARRAY[%(hogql_val_1)s], ARRAY[2]))",
        ),
        ("in(user_id, ('a', 'b'))", '"users"."user_id" IN (%(hogql_val_0)s, %(hogql_val_1)s)'),
        ("notIn(user_id, ('a', 'b'))", '"users"."user_id" NOT IN (%(hogql_val_0)s, %(hogql_val_1)s)'),
        ("user_id IN ['violet', 'amber']", '"users"."user_id" IN (%(hogql_val_0)s, %(hogql_val_1)s)'),
        ("user_id NOT IN ['violet']", '"users"."user_id" NOT IN (%(hogql_val_0)s)'),
        ("in(user_id, ['violet'])", '"users"."user_id" IN (%(hogql_val_0)s)'),
        ("notIn(user_id, [])", "SELECT TRUE FROM"),
        ("user_id IN []", "SELECT FALSE FROM"),
        ("(1, 2) IN []", "SELECT FALSE FROM"),
        ("notIn((1, 2), [])", "SELECT TRUE FROM"),
        ("NULL IN []", "SELECT FALSE FROM"),
        ("NULL NOT IN []", "SELECT TRUE FROM"),
        ("arrayMap(x -> x IN [], [1, 2])", 'transform(ARRAY[1, 2], "x" -> FALSE)'),
        ("arrayFilter(x -> x NOT IN [], [1, 2])", 'filter(ARRAY[1, 2], "x" -> TRUE)'),
        ("arrayMap(x -> in(x, []), [1, 2])", 'transform(ARRAY[1, 2], "x" -> FALSE)'),
        ("user_id IN ['violet', NULL]", '"users"."user_id" IN (%(hogql_val_0)s, NULL)'),
        ("toDateTime(created_at, 'UTC')", 'with_timezone(CAST("users"."created_at" AS TIMESTAMP),'),
        ("toTimeZone(created_at, 'America/Toronto')", "at_timezone(with_timezone(CAST("),
        ("parseDateTime(user_id, '%Y-%m-%d')", 'TRY(date_parse("users"."user_id",'),
        ("dateAdd('day', 2, created_at)", 'date_add(%(hogql_val_0)s, 2, "users"."created_at")'),
        ("dateSub('day', 2, created_at)", 'date_add(%(hogql_val_0)s, -(2), "users"."created_at")'),
        ("date_diff('day', created_at, created_at)", 'date_diff(%(hogql_val_0)s, "users"."created_at"'),
        ("dateTrunc('month', created_at, 'UTC')", "date_trunc(%(hogql_val_0)s, at_timezone("),
        ("toISOWeek(created_at)", 'EXTRACT(WEEK FROM "users"."created_at")'),
        ("toISOYear(created_at)", 'EXTRACT(YEAR_OF_WEEK FROM "users"."created_at")'),
        ("toYYYYMM(created_at)", 'CAST(date_format("users"."created_at", \'%Y%m\') AS INTEGER)'),
        ("toYYYYMMDD(created_at)", 'CAST(date_format("users"."created_at", \'%Y%m%d\') AS INTEGER)'),
        (
            "toYYYYMMDDhhmmss(created_at)",
            'CAST(date_format("users"."created_at", \'%Y%m%d%H%i%s\') AS BIGINT)',
        ),
        ("toLastDayOfWeek(created_at)", "CAST(date_add('day', 5, date_trunc('week',"),
        ("toLastDayOfWeek(created_at, 1)", "CAST(date_add('day', 6, date_trunc('week',"),
        ("toIntervalQuarter(2)", "CAST(2 AS BIGINT) * INTERVAL '3' MONTH"),
        ("toIntervalYear(2)", "CAST(2 AS BIGINT) * INTERVAL '12' MONTH"),
        ("toIntervalWeek(2)", "CAST(2 AS BIGINT) * INTERVAL '7' DAY"),
        ("toIntOrDefault(user_id, 7)", 'COALESCE(TRY_CAST("users"."user_id" AS BIGINT), CAST(7 AS BIGINT))'),
        ("toNullable(user_id)", '"users"."user_id"'),
        ("_toDate(user_id)", 'CAST("users"."user_id" AS DATE)'),
        ("anyIf(user_id, user_id != '')", 'arbitrary("users"."user_id") FILTER (WHERE'),
        ("countIf(user_id, user_id != '')", 'count("users"."user_id") FILTER (WHERE'),
        ("repeat(user_id, 2)", 'ELSE array_join(repeat("users"."user_id", 2), \'\') END'),
        ("5 / 2", "(CAST(5 AS DOUBLE) / CAST(2 AS DOUBLE))"),
        ("divide(5, 2)", "(CAST(5 AS DOUBLE) / CAST(2 AS DOUBLE))"),
        ("not(user_id = '')", '(NOT ("users"."user_id" = %(hogql_val_0)s))'),
        ("toMonday(created_at)", 'CAST(date_trunc(\'week\', "users"."created_at") AS DATE)'),
        ("yesterday()", "date_add('day', -1, CURRENT_DATE)"),
        ("md5(user_id)", 'to_hex(md5(to_utf8(CAST("users"."user_id" AS VARCHAR))))'),
        ("power(2, 3)", "power(2, 3)"),
        ("ln(2)", "ln(2)"),
        ("log2(2)", "log2(2)"),
        ("cbrt(8)", "cbrt(8)"),
        ("degrees(1)", "degrees(1)"),
        ("radians(1)", "radians(1)"),
        ("pi()", "pi()"),
        ("sign(-1)", "sign(-1)"),
        ("sin(1)", "sin(1)"),
        ("cos(1)", "cos(1)"),
        ("tan(1)", "tan(1)"),
        ("asin(1)", "asin(1)"),
        ("acos(1)", "acos(1)"),
        ("atan(1)", "atan(1)"),
        ("atan2(1, 2)", "atan2(1, 2)"),
        ("trim(' x ', ' ')", "trim(%(hogql_val_0)s, %(hogql_val_1)s)"),
        ("ltrim(' x ', ' ')", "ltrim(%(hogql_val_0)s, %(hogql_val_1)s)"),
        ("rtrim(' x ', ' ')", "rtrim(%(hogql_val_0)s, %(hogql_val_1)s)"),
        ("reverse(user_id)", 'reverse("users"."user_id")'),
        ("replace(user_id, 'a', 'b')", 'replace("users"."user_id",'),
        ("lpad(user_id, 3, '0')", 'lpad("users"."user_id", 3,'),
        ("rpad(user_id, 3, '0')", 'rpad("users"."user_id", 3,'),
        ("e()", "e()"),
        ("toIntervalDay(2)", "(CAST(2 AS BIGINT) * INTERVAL '1' DAY)"),
        ("JSONExtractArrayRaw(properties, 'items')", "transform(CAST(json_extract("),
        ("user_id IN ['a', 'b']", '("users"."user_id" IN ('),
        ("toDateTime(123)", "CAST(from_unixtime(CAST(123 AS DOUBLE)) AS TIMESTAMP)"),
        ("arrayMax([1, 2])", "array_max(ARRAY[1, 2])"),
        ("arraySum([1, 2])", "reduce(ARRAY[1, 2], CAST(0 AS DOUBLE)"),
        ("coalesce(nullIf(true, 0), false)", "coalesce(nullif(CAST(true AS INTEGER), 0), CAST(false AS INTEGER))"),
        ("not(2)", "NOT CAST(2 AS BOOLEAN)"),
        ("JSONHas(properties, user_id)", 'json_format(CAST(CAST("users"."user_id" AS VARCHAR) AS JSON))'),
        ("JSONExtractString(properties)", 'json_extract_scalar("users"."properties",'),
        ("created_at + 2", "date_add('second', CAST(2 AS BIGINT)"),
        ("['a'][3]", "element_at(ARRAY[%(hogql_val_0)s], 3)"),
        ("divideDecimal(toDecimal(1, 10), toDecimal(100, 10))", "(CAST(1 AS DECIMAL(38, 10)) /"),
        (
            "divideDecimal(toDecimal(1, 10), toDecimal(100, 10), 4)",
            "AS DECIMAL(38, 4))",
        ),
        ("arrayAll(x -> x > 0, [1, 2])", 'all_match(ARRAY[1, 2], "x" -> ("x" > 0))'),
        (
            "arrayIntersect([1, 2], [2, 3], [2, 4])",
            "array_intersect(array_intersect(array_distinct(ARRAY[1, 2]), ARRAY[2, 3]), ARRAY[2, 4])",
        ),
        (
            "positionCaseInsensitive(user_id, 'A', 2)",
            'CASE WHEN strpos(lower(substr("users"."user_id", 2)), lower(%(hogql_val_0)s)) = 0 THEN 0',
        ),
        ("cutFragment(user_id)", "regexp_replace(\"users\".\"user_id\", '#.*$', '')"),
        (
            "cutQueryStringAndFragment(user_id)",
            "regexp_replace(\"users\".\"user_id\", '[?#].*$', '')",
        ),
        ("cutQueryString(user_id)", "regexp_replace(\"users\".\"user_id\", '\\?.*$', '')"),
        ("path(user_id)", 'url_extract_path("users"."user_id")'),
        ("decodeURLComponent(user_id)", 'url_decode("users"."user_id")'),
        ("trimLeft(user_id)", 'ltrim("users"."user_id")'),
        ("trimRight(user_id)", 'rtrim("users"."user_id")'),
        ("toFloatOrNull(user_id)", 'TRY_CAST("users"."user_id" AS DOUBLE)'),
        ("_toInt16(12)", "CAST(12 AS SMALLINT)"),
        ("to_date(created_at)", 'CAST("users"."created_at" AS DATE)'),
        ("map('key', 1)", "map(ARRAY[%(hogql_val_0)s], ARRAY[1])"),
        (
            "transform(user_id, ['a'], ['A'], 'other')",
            'CASE WHEN contains(ARRAY[%(hogql_val_0)s], "users"."user_id") '
            "THEN element_at(ARRAY[%(hogql_val_1)s], array_position(",
        ),
        ("first_value(user_id)", 'arbitrary("users"."user_id")'),
        (
            "toStartOfDay(created_at, 'America/Toronto')",
            "date_trunc('day', at_timezone(with_timezone(CAST(",
        ),
        ("like(user_id, '%example')", '("users"."user_id" LIKE %(hogql_val_0)s)'),
    ],
)
def test_prints_safe_pr_91053_function_mappings(expression: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT {expression} FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert expected in sql


def test_prints_typed_json_map_and_trino_try_cast() -> None:
    query = parse_select("SELECT JSONExtract(properties, 'Map(String, Float64)') FROM users")
    assert isinstance(query, ast.SelectQuery)
    query.select.append(ast.TryCast(expr=ast.Field(chain=["users", "user_id"]), type_name="BIGINT"))

    sql, _ = prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert "AS MAP(VARCHAR, JSON))" in sql
    assert "TRY_CAST(__hogql_json_value AS DOUBLE)" in sql
    assert "CAST(0 AS DOUBLE)" in sql
    assert 'TRY_CAST("users"."user_id" AS BIGINT)' in sql


def test_rejects_parse_datetime_format_without_matching_trino_semantics() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT parseDateTime(user_id, '%Q') FROM users"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_DATETIME_FORMAT_UNSUPPORTED"


def test_rejects_map_from_arrays_with_duplicate_keys() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT mapFromArrays(['a', 'a'], [1, 2])"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_MAP_DUPLICATE_KEYS_UNSUPPORTED"


def test_guards_dynamic_map_from_arrays_without_discarding_keys() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT mapFromArrays([user_id, user_id], [1, 2]) FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert "all_match(__hogql_args[1], __hogql_key -> __hogql_key IS NOT NULL)" in sql
    assert "cardinality(array_distinct(__hogql_args[1])) = cardinality(__hogql_args[1])" in sql
    assert "map(__hogql_args[1], __hogql_args[2])" in sql
    assert "fail('mapFromArrays requires equal-length arrays with unique, non-null keys')" in sql


@pytest.mark.parametrize(
    "expression",
    [
        "_toInt16(40000)",
    ],
)
def test_rejects_pr_91053_shortcuts_without_matching_trino_semantics(expression: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select(f"SELECT {expression}"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_FUNCTION_UNSUPPORTED"


@pytest.mark.parametrize("identifier", ["parameter?", "parameter%", "nul\0identifier"])
def test_rejects_trino_identifiers_that_can_collide_with_parameter_binding(identifier: str) -> None:
    with pytest.raises(QueryError):
        escape_trino_identifier(identifier)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("any(user_id) OVER ()", 'arbitrary("users"."user_id") OVER ()'),
        ("groupArray(user_id) OVER ()", 'array_agg("users"."user_id") OVER ()'),
        (
            "countIf(user_id != '') OVER ()",
            'count_if(("users"."user_id" != %(hogql_val_0)s)) OVER ()',
        ),
        (
            "stddevPopIf(length(user_id), length(user_id) > 1) OVER ()",
            'stddev_pop(IF((length("users"."user_id") > 1), length("users"."user_id"), NULL)) OVER ()',
        ),
        (
            "quantileExactIf(0.5)(length(user_id), length(user_id) > 1) OVER ()",
            "array_sort(filter(array_agg(IF(",
        ),
    ],
)
def test_prints_semantics_safe_trino_window_functions(expression: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT {expression} FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert expected in sql


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("uniqExact(user_id) OVER ()", 'count(DISTINCT "users"."user_id") OVER ()'),
        (
            "uniqExactIf(user_id, length(user_id) > 1) OVER ()",
            'count(DISTINCT IF((length("users"."user_id") > 1), "users"."user_id", NULL)) OVER ()',
        ),
    ],
)
def test_prints_distinct_trino_window_functions(expression: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT {expression} FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert expected in sql


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "formatDateTime(created_at, '%Y-%m-%d', 'UTC')",
            'date_format(at_timezone(with_timezone(CAST("users"."created_at" AS TIMESTAMP), \'UTC\'),',
        ),
        (
            "toDateTime64('2026-01-02 03:04:05', 3, 'UTC')",
            "with_timezone(CAST(%(hogql_val_0)s AS TIMESTAMP(3)), %(hogql_val_1)s)",
        ),
        (
            "topK(2)(user_id)",
            'transform(slice(array_sort(map_entries(histogram("users"."user_id"))',
        ),
    ],
)
def test_prints_extended_trino_function_forms(expression: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT {expression} FROM users"),
        _context_with_trino_table(),
        "trino",
    )

    assert expected in sql


def test_unqualifies_order_by_when_output_alias_shadows_relation_name() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "WITH runs AS (SELECT created_at AS day FROM users) "
            "SELECT runs.day AS day, count() AS runs FROM runs GROUP BY day ORDER BY day DESC, runs DESC"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert "ORDER BY 1 DESC, 2 DESC" in sql


def test_lowers_offset_in_frame_over_a_full_partition() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT leadInFrame(user_id, 1, '') OVER ("
            "ORDER BY created_at ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING"
            ") FROM users"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert 'lead("users"."user_id", 1, %(hogql_val_0)s) OVER (ORDER BY "users"."created_at" ASC)' in sql
    assert "ROWS BETWEEN" not in sql


def test_lowers_lag_in_frame_when_the_offset_is_inside_the_frame() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT lagInFrame(created_at) OVER ("
            "ORDER BY created_at ROWS BETWEEN 1 PRECEDING AND CURRENT ROW"
            ") FROM users"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert 'lag("users"."created_at") OVER (ORDER BY "users"."created_at" ASC)' in sql
    assert "ROWS BETWEEN" not in sql


@pytest.mark.parametrize(
    ("expression", "feature_code"),
    [
        ("lag(user_id) OVER ()", "TRINO_WINDOW_ORDER_REQUIRED"),
        (
            "row_number() OVER (ORDER BY created_at ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)",
            "TRINO_WINDOW_FRAME_UNSUPPORTED",
        ),
    ],
)
def test_rejects_unsafe_trino_window_shapes(expression: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select(f"SELECT {expression} FROM users"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == feature_code


@pytest.mark.parametrize("modifier", ["distinct", "filter"])
def test_rejects_aggregate_modifiers_on_scalar_trino_calls(modifier: str) -> None:
    query = parse_select("SELECT toDecimal(user_id, 2) FROM users")
    assert isinstance(query, ast.SelectQuery)
    call = query.select[0]
    assert isinstance(call, ast.Call)
    if modifier == "distinct":
        call.distinct = True
    else:
        call.filter_expr = ast.Constant(value=True)

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert error.value.feature_code == "TRINO_SCALAR_FUNCTION_MODIFIER_UNSUPPORTED"


def test_lowers_left_any_join_by_deduplicating_the_right_relation() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT users.user_id, other.created_at FROM users "
            "LEFT ANY JOIN users AS other ON users.user_id = other.user_id"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert "LEFT ANY JOIN" not in sql
    assert 'row_number() OVER (PARTITION BY "__hogql_any_source_0"."user_id")' in sql
    assert 'WHERE ("__hogql_any_ranked_0"."__hogql_any_row_0" = 1)' in sql
    assert ') AS "other" ON ("users"."user_id" = "other"."user_id")' in sql


def test_lowers_multi_key_any_join_with_a_right_expression() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT users.user_id, other.created_at FROM users LEFT ANY JOIN users AS other "
            "ON users.user_id = toString(other.user_id) AND users.created_at = other.created_at"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert 'PARTITION BY CAST("__hogql_any_source_0"."user_id" AS VARCHAR), "__hogql_any_source_0"."created_at"' in sql
    assert '"users"."user_id" = CAST("other"."user_id" AS VARCHAR)' in sql


def test_lowers_unaliased_left_any_join() -> None:
    context = _context_with_trino_table()
    assert context.database is not None
    context.database.tables.add_child(
        TableNode(
            name="people",
            table=DirectTrinoTable(
                name="people",
                fields={
                    "user_id": StringDatabaseField(name="user_id", nullable=False),
                    "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
                },
                external_data_source_id="source-id",
                trino_catalog="ducklake",
                trino_schema="analytics",
                trino_table_name="people",
                has_complete_columns=False,
            ),
        )
    )
    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT users.user_id, people.created_at FROM users LEFT ANY JOIN people ON users.user_id = people.user_id"
        ),
        context,
        "trino",
    )

    assert "LEFT ANY JOIN" not in sql
    assert ') AS "people" ON ("users"."user_id" = "people"."user_id")' in sql


def test_lowers_any_join_to_the_deduplicated_trino_persons_relation() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
        trino_table_locators={
            "events": ("tenant", "posthog", "events"),
            "persons": ("tenant", "posthog", "persons"),
            "person_distinct_ids": ("tenant", "posthog", "person_distinct_ids"),
            "raw_person_distinct_ids": ("tenant", "posthog", "person_distinct_ids"),
        },
    )

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT persons.properties.email FROM events LEFT ANY JOIN persons ON events.person_id = persons.id"
        ),
        context,
        "trino",
    )

    assert "LEFT ANY JOIN" not in sql
    assert 'FROM "tenant"."posthog"."persons" GROUP BY 1) AS "persons"' in sql
    assert '"persons"."properties___email"' in sql


def test_lowers_left_any_join_against_a_cte() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "WITH right_rows AS (SELECT user_id, created_at FROM users) "
            "SELECT users.user_id, other.created_at FROM users "
            "LEFT ANY JOIN right_rows AS other ON users.user_id = other.user_id"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert "LEFT ANY JOIN" not in sql
    assert 'row_number() OVER (PARTITION BY "__hogql_any_source_0"."user_id")' in sql
    assert '"right_rows" AS "__hogql_any_source_0"' in sql


@pytest.mark.parametrize(
    ("join", "constraint", "feature_code"),
    [
        ("RIGHT ANY JOIN", "users.user_id = other.user_id", "TRINO_ANY_JOIN_MODE_UNSUPPORTED"),
        ("LEFT ANY JOIN", "users.user_id < other.user_id", "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED"),
    ],
)
def test_rejects_unsafe_any_join_shapes(join: str, constraint: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select(f"SELECT users.user_id FROM users {join} users AS other ON {constraint}"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == feature_code


@pytest.mark.parametrize(
    ("join", "expected"),
    [
        ("ALL INNER JOIN", "INNER JOIN"),
        ("LEFT ALL JOIN", "LEFT JOIN"),
        ("RIGHT ALL JOIN", "RIGHT JOIN"),
        ("FULL ALL JOIN", "FULL JOIN"),
    ],
)
def test_lowers_clickhouse_all_join_to_standard_trino_join(join: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(f"SELECT users.user_id FROM users {join} users AS other ON users.user_id = other.user_id"),
        _context_with_trino_table(),
        "trino",
    )

    assert f" {expected} " in sql
    assert f" {join} " not in sql


def test_removes_noop_sample_one_for_trino() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select("SELECT user_id FROM users SAMPLE 1"),
        _context_with_trino_table(),
        "trino",
    )

    assert "SAMPLE" not in sql


@pytest.mark.parametrize(
    ("query", "feature_code"),
    [
        ("SELECT user_id FROM users SAMPLE 0.5", "TRINO_SAMPLE_UNSUPPORTED"),
        (
            "SELECT * FROM users PIVOT(count(user_id) FOR created_at IN ('2026-01-01'))",
            "TRINO_PIVOT_UNSUPPORTED",
        ),
        (
            "SELECT * FROM users UNPIVOT(value FOR key IN (user_id))",
            "TRINO_UNPIVOT_UNSUPPORTED",
        ),
    ],
)
def test_rejects_clickhouse_query_clauses_without_safe_trino_semantics(query: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino")

    assert error.value.feature_code == feature_code


def test_rejects_source_ast_with_clickhouse_settings() -> None:
    query = parse_select("SELECT user_id FROM users")
    assert isinstance(query, ast.SelectQuery)
    query.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(query, _context_with_trino_table(), "trino")

    assert error.value.feature_code == "TRINO_SETTINGS_UNSUPPORTED"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("WITH items AS (SELECT ['a'] AS xs) SELECT empty(xs) FROM items", 'cardinality("items"."xs")'),
        ("WITH items AS (SELECT ['a'] AS xs) SELECT xs != '[]' FROM items", 'cardinality("items"."xs")'),
        (
            "WITH items AS (SELECT JSONExtractArrayRaw(properties, 'items') AS xs FROM users) SELECT empty(xs) FROM items",
            'cardinality("items"."xs")',
        ),
    ],
)
def test_preserves_array_types_across_cte_boundaries(query: str, expected: str) -> None:
    sql, _ = prepare_and_print_ast(parse_select(query), _context_with_trino_table(), "trino")

    assert expected in sql


def test_union_keeps_common_ctes_in_scope_for_every_branch() -> None:
    sql, _ = prepare_and_print_ast(
        parse_select(
            "WITH source AS (SELECT user_id FROM users) SELECT user_id FROM source UNION ALL SELECT user_id FROM source"
        ),
        _context_with_trino_table(),
        "trino",
    )

    assert sql.startswith('WITH "source" AS (')
    assert sql.count('FROM "source"') == 2
    assert ") UNION ALL (" in sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT user_id FROM users ORDER BY created_at DESC LIMIT 2 BY user_id LIMIT 5 OFFSET 1",
        "SELECT user_id FROM users ORDER BY toStartOfDay(created_at) DESC LIMIT 2 BY user_id",
        "SELECT user_id AS id FROM users ORDER BY id DESC LIMIT 2 BY id",
        "SELECT user_id, created_at FROM users ORDER BY 2 DESC LIMIT 2 BY user_id",
        "SELECT user_id, created_at FROM users ORDER BY 2 DESC LIMIT 2 BY 1",
        "SELECT user_id AS __hogql_order_0, created_at AS __hogql_limit_by_row_0 "
        "FROM users ORDER BY toStartOfDay(created_at) DESC LIMIT 2 BY user_id",
        "SELECT a.created_at FROM users a JOIN users b ON a.user_id = b.user_id "
        "ORDER BY b.created_at DESC LIMIT 2 BY a.user_id",
        "SELECT user_id, row_number() OVER (ORDER BY created_at) AS position "
        "FROM users QUALIFY position = 1 ORDER BY created_at DESC LIMIT 3",
        "SELECT user_id, count() AS total FROM users GROUP BY user_id ORDER BY total DESC LIMIT 2 BY user_id",
        "SELECT user_id, user_id = toString(1) AS bucket, row_number() OVER (ORDER BY user_id) AS rn "
        "FROM users QUALIFY rn > 0 ORDER BY user_id = toString(true) DESC LIMIT 1",
        "SELECT user_id, user_id = toString(1) AS bucket, row_number() OVER (ORDER BY user_id) AS rn "
        "FROM users QUALIFY rn > 0 ORDER BY user_id = toString(1.0) DESC LIMIT 1",
        "SELECT properties.color FROM users ORDER BY user_id LIMIT 1 BY user_id",
        "SELECT properties.color, row_number() OVER (ORDER BY user_id) AS rn "
        "FROM users QUALIFY rn = 1 ORDER BY user_id",
    ],
)
def test_wrapper_sort_projections_preserve_output(query: str, snapshot: SnapshotAssertion) -> None:
    context = _context_with_trino_table()
    sql, node = prepare_and_print_ast(parse_select(query), context, "trino")

    assert isinstance(node, ast.SelectQuery)
    assert node.select_from is not None
    inner = node.select_from.table
    assert isinstance(inner, ast.SelectQuery)
    for expr in node.select:
        while isinstance(expr, ast.Alias):
            expr = expr.expr
        assert isinstance(expr, ast.Field)
    original = parse_select(query)
    assert isinstance(original, ast.SelectQuery)
    assert len(node.select) == len(original.select)
    assert inner.order_by is None
    assert inner.limit is None
    assert inner.limit_by is None
    assert inner.qualify is None
    assert (sql, context.values) == snapshot


@pytest.mark.parametrize(
    ("query", "feature_code"),
    [
        (
            "SELECT user_id FROM users GROUP BY user_id ORDER BY created_at LIMIT 1 BY user_id",
            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
        ),
        (
            "SELECT user_id, count() AS total FROM users GROUP BY user_id ORDER BY max(created_at) DESC LIMIT 2 BY user_id",
            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
        ),
        ("SELECT user_id FROM users ORDER BY count() LIMIT 1 BY user_id", "TRINO_WRAPPER_ORDER_NOT_PROJECTED"),
        (
            "SELECT user_id FROM users ORDER BY count() + 1 LIMIT 1 BY user_id",
            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
        ),
        (
            "SELECT DISTINCT user_id, row_number() OVER (ORDER BY user_id) AS position "
            "FROM users QUALIFY position = 1 ORDER BY created_at",
            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
        ),
        ("SELECT user_id FROM users ORDER BY 2 LIMIT 1 BY user_id", "TRINO_POSITIONAL_REFERENCE_INVALID"),
        ("SELECT user_id FROM users LIMIT 1 BY 2", "TRINO_POSITIONAL_REFERENCE_INVALID"),
        (
            "SELECT DISTINCT user_id, user_id = toString(1) AS bucket, row_number() OVER (ORDER BY user_id) AS rn "
            "FROM users QUALIFY rn > 0 ORDER BY user_id = toString(true)",
            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
        ),
        (
            "SELECT user_id FROM users ORDER BY row_number() OVER (ORDER BY created_at) LIMIT 1 BY user_id",
            "TRINO_LIMIT_BY_WINDOW_UNSUPPORTED",
        ),
        (
            "SELECT user_id, row_number() OVER (ORDER BY created_at) AS rn FROM users ORDER BY 2 LIMIT 1 BY user_id",
            "TRINO_LIMIT_BY_WINDOW_UNSUPPORTED",
        ),
        (
            "SELECT user_id, row_number() OVER (ORDER BY created_at) AS rn FROM users LIMIT 1 BY rn",
            "TRINO_LIMIT_BY_WINDOW_UNSUPPORTED",
        ),
    ],
)
def test_wrapper_rejects_unsafe_sort_or_partition(query: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError, match=feature_code):
        prepare_and_print_ast(
            parse_select(query),
            _context_with_trino_table(),
            "trino",
        )


@pytest.mark.parametrize(
    ("expression", "group_by"),
    [
        ("properties.color", None),
        ("toStartOfMonth(toTimeZone(created_at, 'UTC'))", None),
        ("notEmpty(properties.color)", None),
        ("concat(user_id, 'suffix')", None),
        pytest.param("2", "dimension", id="integer_alias"),
        pytest.param("0", "dimension", id="zero_alias"),
    ],
)
def test_grouping_reuses_projected_expression(
    expression: str, group_by: str | None, snapshot: SnapshotAssertion
) -> None:
    context = _context_with_trino_table()
    sql, node = prepare_and_print_ast(
        parse_select(f"SELECT {expression} AS dimension, count() FROM users GROUP BY {group_by or expression}"),
        context,
        "trino",
    )

    assert isinstance(node, ast.SelectQuery)
    assert node.group_by is not None
    assert len(node.group_by) == 1
    assert isinstance(node.group_by[0], ast.PositionalRef)
    assert node.group_by[0].index == 1
    assert (sql, context.values) == snapshot


def test_lowered_property_timestamp_is_not_constant(snapshot: SnapshotAssertion) -> None:
    context = _context_with_trino_table()
    sql, node = prepare_and_print_ast(parse_select("SELECT toDateTime(properties.cutoff) FROM users"), context, "trino")

    assert isinstance(node, ast.SelectQuery)
    expr = node.select[0]
    assert isinstance(expr, ast.Call)
    argument = expr.args[0]
    while isinstance(argument, ast.Alias):
        argument = argument.expr
    assert isinstance(argument, ast.PropertyAccess)
    assert not is_time_or_interval_constant(expr)
    assert (sql, context.values) == snapshot


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.user_id FROM users a JOIN users b ON a.user_id = b.user_id GROUP BY b.user_id",
        "SELECT user_id AS id FROM users GROUP BY concat(id, 'suffix')",
        "SELECT properties.color, count() FROM users GROUP BY properties.shape",
        "SELECT user_id, count() FROM users GROUP BY ROLLUP(user_id)",
        "SELECT 2, count() FROM users GROUP BY 2",
        "SELECT user_id = toString(1) AS bucket, count() FROM users GROUP BY user_id = toString(true)",
    ],
)
def test_grouping_does_not_replace_different_or_nested_expressions(query: str, snapshot: SnapshotAssertion) -> None:
    context = _context_with_trino_table()
    sql, node = prepare_and_print_ast(parse_select(query), context, "trino")

    assert isinstance(node, ast.SelectQuery)
    assert node.group_by is not None
    assert not isinstance(node.group_by[0], ast.PositionalRef)
    assert (sql, context.values) == snapshot
