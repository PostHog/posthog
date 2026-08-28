import pytest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.transforms.trino.validate import TrinoLoweringError


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


def test_rejects_postgres_any_as_min_approximation() -> None:
    with pytest.raises(QueryError, match="not supported in the Trino dialect"):
        print_prepared_ast(ast.Call(name="any", args=[ast.Constant(value=1)]), HogQLContext(), "trino")


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


def test_limit_by_returns_stable_lowering_error() -> None:
    with pytest.raises(TrinoLoweringError) as error:
        prepare_and_print_ast(
            parse_select("SELECT user_id FROM users LIMIT 1 BY user_id"),
            _context_with_trino_table(),
            "trino",
        )

    assert error.value.feature_code == "TRINO_LIMIT_BY_NOT_LOWERED"
