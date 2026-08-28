import pytest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError


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
        ("JSON_VALUE(user_id, '$.key')", 'json_value("users"."user_id", \'$.key\')'),
        (
            "quantileIf(0.9)(length(user_id), user_id != '')",
            'approx_percentile(length("users"."user_id"), 0.9) FILTER',
        ),
        ("argMax(user_id, created_at)", 'max_by("users"."user_id", "users"."created_at")'),
    ],
)
def test_prints_core_trino_expression_mappings(expression: str, expected: str) -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(parse_select(f"SELECT {expression} FROM users"), context, "trino")

    assert expected in sql


def test_prints_json_paths_as_bound_values() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(
        parse_select("SELECT JSONExtractString(user_id, 'key.with.dot', 2) FROM users"),
        context,
        "trino",
    )

    assert 'json_extract_scalar("users"."user_id", %(hogql_val_0)s)' in sql
    assert context.values == {"hogql_val_0": '$."key.with.dot"[2]'}


def test_prints_empty_according_to_resolved_argument_type() -> None:
    context = _context_with_trino_table()

    sql, _ = prepare_and_print_ast(parse_select("SELECT empty(''), notEmpty([1])"), context, "trino")

    assert sql == (
        "SELECT (%(hogql_val_0)s IS NULL AND %(hogql_val_0)s = ''), "
        "(ARRAY[1] IS NOT NULL AND cardinality(ARRAY[1]) > 0)"
    )


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
        'CROSS JOIN UNNEST(ARRAY[1, 2]) AS "__trino_unnest_0" ("item")' in sql
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
    assert 'CROSS JOIN UNNEST(ARRAY[1, 2]) AS "__trino_array_function_0" ("value_0")' in sql


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
