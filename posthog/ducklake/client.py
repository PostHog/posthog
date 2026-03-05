from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.conninfo import make_conninfo

from posthog.ducklake.common import get_duckgres_config, sanitize_ducklake_identifier

if TYPE_CHECKING:
    from posthog.schema import HogQLQuery


@dataclass
class DuckLakeQueryResult:
    columns: list[str]
    types: list[str]
    results: list[list[Any]]
    sql: str
    hogql: str | None = None


@dataclass
class DuckLakeTableResult:
    schema_name: str
    table_name: str
    row_count: int


def _make_duckgres_conninfo(team_id: int) -> str:
    config = get_duckgres_config(team_id)
    return make_conninfo(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        sslmode="require",
    )


def compile_hogql_to_ducklake_sql(team_id: int, query: HogQLQuery) -> tuple[str, str]:
    """Compile a HogQLQuery to Postgres-dialect SQL for DuckLake.

    Returns (postgres_sql, hogql_pretty) tuple.
    """
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.printer.utils import prepare_and_print_ast

    parsed = parse_select(query.query)
    context = HogQLContext(team_id=team_id, enable_select_queries=True)
    postgres_sql, _ = prepare_and_print_ast(parsed, context, dialect="postgres")
    hogql_pretty, _ = prepare_and_print_ast(parsed, context, dialect="hogql")
    return postgres_sql, hogql_pretty


def execute_ducklake_query(
    team_id: int,
    *,
    sql: str | None = None,
    query: HogQLQuery | None = None,
) -> DuckLakeQueryResult:
    """Execute a query against a team's duckgres server.

    Accepts either raw SQL or a HogQLQuery (which gets compiled to
    Postgres-dialect SQL). Exactly one of `sql` or `query` must be provided.
    """
    if sql and query:
        raise ValueError("Provide either sql or query, not both")
    if not sql and not query:
        raise ValueError("Provide either sql or query")

    hogql_pretty: str | None = None
    if query:
        sql, hogql_pretty = compile_hogql_to_ducklake_sql(team_id, query)

    assert sql is not None

    conninfo = _make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc.name for desc in cur.description] if cur.description else []
            types = [str(desc.type_code) for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
    return DuckLakeQueryResult(
        columns=columns,
        types=types,
        results=[list(r) for r in rows],
        sql=sql,
        hogql=hogql_pretty,
    )


def execute_ducklake_create_table(team_id: int, sql: str, schema_name: str, table_name: str) -> DuckLakeTableResult:
    """Execute a query via duckgres and materialize the result as a DuckLake table.

    Creates or replaces a table in the given schema using CREATE OR REPLACE TABLE ... AS.
    The table is stored natively in DuckLake (Parquet on S3 + Postgres catalog metadata).
    """
    safe_schema = sanitize_ducklake_identifier(schema_name, default_prefix="shadow")
    safe_table = sanitize_ducklake_identifier(table_name, default_prefix="model")
    qualified = f"{safe_schema}.{safe_table}"

    conninfo = _make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {safe_schema}")
            cur.execute(f"CREATE OR REPLACE TABLE {qualified} AS {sql}")

    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {qualified}")
            row = cur.fetchone()
            row_count = int(row[0]) if row else 0
    return DuckLakeTableResult(
        schema_name=safe_schema,
        table_name=safe_table,
        row_count=row_count,
    )
