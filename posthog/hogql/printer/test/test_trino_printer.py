import sqlite3
from contextlib import closing

import pytest
from unittest import mock

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField, StringJSONDatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.transpiler import TrinoTranspilerInput, transpile_prepared_hogql_to_trino
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
                    "user_id": StringDatabaseField(name="user_id", nullable=False),
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


def test_prepared_trino_transpiler_does_not_rebuild_the_schema_database() -> None:
    preparation_context = _context_with_trino_table()
    prepared = prepare_ast_for_printing(
        parse_select("SELECT user_id FROM users WHERE user_id = 'person-1'"), preparation_context, "trino"
    )
    assert prepared is not None
    assert preparation_context.database is not None

    transpiler_input = TrinoTranspilerInput(
        node=prepared,
        values=tuple(preparation_context.values.items()),
        table_locators=tuple(preparation_context.trino_table_locators.items()),
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

    assert transpiled.sql == (
        'SELECT "users"."user_id" FROM "ducklake"."analytics"."users" AS "users" '
        'WHERE ("users"."user_id" = %(hogql_val_0)s)'
    )
    assert transpiled.values == {"hogql_val_0": "person-1"}


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


def test_distinct_limit_by_returns_stable_lowering_error() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT DISTINCT user_id FROM users LIMIT 1 BY user_id"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_LIMIT_BY_DISTINCT_UNSUPPORTED"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("arrayMap(value -> value + 1, [1, 2])", 'transform(ARRAY[1, 2], "value" -> ("value" + 1))'),
        ("arrayFilter(value -> value > 1, [1, 2])", 'filter(ARRAY[1, 2], "value" -> ("value" > 1))'),
        ("arrayElement([1, 2], 1)", "element_at(ARRAY[1, 2], 1)"),
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
    ],
)
def test_prints_core_trino_expression_mappings(expression: str, expected: str) -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(parse_select(f"SELECT {expression} FROM users"), context, "trino")

    assert expected in sql


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


def test_prints_json_paths_as_bound_values() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT JSONExtractString(user_id, 'key.with.dot', 2) FROM users"),
        context,
        "trino",
    )

    assert 'json_extract_scalar("users"."user_id", %(hogql_val_0)s)' in sql
    assert context.values == {"hogql_val_0": '$["key.with.dot"][2]'}


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


def test_lowers_clickhouse_select_alias_references_to_expressions() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select(
            "SELECT user_id AS account_id, count() AS total FROM users "
            "GROUP BY account_id HAVING total > 0 ORDER BY total"
        ),
        context,
        "trino",
    )

    assert "GROUP BY 1" in sql
    assert "HAVING (count(*) > 0)" in sql
    assert "ORDER BY count(*) ASC" in sql


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


def test_rejects_function_argument_shapes_with_stable_error() -> None:
    context = _context_with_trino_table()

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(parse_select("SELECT JSONExtractKeysAndValuesRaw('{}', 'extra')"), context, "trino")

    assert error.value.feature_code == "TRINO_FUNCTION_ARGUMENTS_UNSUPPORTED"


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


def test_rejects_unbounded_numbers_input() -> None:
    context = HogQLContext(
        database=Database(include_posthog_tables=True),
        modifiers=_trino_modifiers(),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )

    with pytest.raises(TrinoLoweringError, match="constant integer arguments") as error:
        prepare_and_print_ast(parse_select("SELECT number FROM numbers(number)"), context, "trino")

    assert error.value.feature_code == "TRINO_NUMBERS_NON_CONSTANT_ARGUMENT"


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


def test_rejects_multi_array_join_with_different_cardinality_semantics() -> None:
    context = _context_with_trino_table()

    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT first FROM users ARRAY JOIN [1] AS first, [2] AS second"),
            context,
            "trino",
        )

    assert error.value.feature_code == "TRINO_ARRAY_JOIN_MULTIPLE_ARRAYS_UNSUPPORTED"


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
            'map_entries(CAST(json_extract("users"."properties", %(hogql_val_0)s) AS MAP(VARCHAR, DOUBLE)))',
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

    assert "AS MAP(VARCHAR, DOUBLE))" in sql
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


@pytest.mark.parametrize(
    "expression",
    [
        "formatReadableTimeDelta(1)",
        "intDiv(5, 2)",
        "medianIf(1, true)",
        "multiplyDecimal(1, 2)",
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
    ("expression", "feature_code"),
    [
        ("lag(user_id) OVER ()", "TRINO_WINDOW_ORDER_REQUIRED"),
        (
            "row_number() OVER (ORDER BY created_at ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)",
            "TRINO_WINDOW_FRAME_UNSUPPORTED",
        ),
        ("lagInFrame(user_id) OVER (ORDER BY created_at)", "TRINO_LAG_IN_FRAME_UNSUPPORTED"),
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
        ("WITH 1 AS scalar_value SELECT scalar_value FROM users", "TRINO_SCALAR_CTE_UNSUPPORTED"),
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
