from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg import sql as psql
from psycopg.conninfo import make_conninfo

from posthog.ducklake.common import get_duckgres_config_for_org, is_dev_mode, sanitize_ducklake_identifier

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
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0


def make_duckgres_conninfo(team_id: int, *, organization_id: str | None = None) -> str:
    from posthog.ducklake.common import _duckgres_dev_config, _get_org_id_for_team

    if is_dev_mode():
        config = _duckgres_dev_config()
    else:
        org_id = organization_id or _get_org_id_for_team(team_id)
        config = get_duckgres_config_for_org(org_id)
    return make_conninfo(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        sslmode="require",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
        sslrootcert="/tmp/no.txt",
    )


# TODO: remove hardcoded schemas and derive the search path from the team's
# data warehouse sources / DAG configuration instead
_SEARCH_PATH_SCHEMAS = ["revenue", "stripe", "billing_public", "credit", "posthog"]


def _set_search_path(conn: psycopg.Connection[Any], extra_schemas: list[str] | None = None) -> None:
    schemas = (extra_schemas or []) + _SEARCH_PATH_SCHEMAS
    literal = psql.Literal(",".join(schemas))
    sql = psql.SQL("SET search_path TO {}").format(literal)
    conn.execute(sql)


def compile_hogql_to_ducklake_sql(team_id: int, query: HogQLQuery) -> tuple[str, dict[str, object], str]:
    """Compile a HogQLQuery to Postgres-dialect SQL for DuckLake.

    Returns ``(postgres_sql, values, hogql_pretty)``. The ``values`` dict holds
    parameter bindings for ``psycopg``'s ``%(name)s`` placeholders embedded in
    ``postgres_sql``; callers must pass it to ``cursor.execute(sql, values)`` or
    the query will fail with an unbound-placeholder error.
    """
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.printer.utils import prepare_and_print_ast

    parsed = parse_select(query.query)
    # Separate context for the Postgres print — the HogQL round-trip below shouldn't
    # contribute to ``postgres_context.values``.
    postgres_context = HogQLContext(team_id=team_id, enable_select_queries=True)
    postgres_sql, _ = prepare_and_print_ast(parsed, postgres_context, dialect="postgres")

    hogql_context = HogQLContext(team_id=team_id, enable_select_queries=True)
    hogql_pretty, _ = prepare_and_print_ast(parsed, hogql_context, dialect="hogql")

    return postgres_sql, dict(postgres_context.values), hogql_pretty


def execute_ducklake_query(
    team_id: int,
    *,
    sql: str | None = None,
    query: HogQLQuery | None = None,
    organization_id: str | None = None,
) -> DuckLakeQueryResult:
    """Execute a query against a team's duckgres server.

    Accepts either raw SQL or a HogQLQuery (which gets compiled to
    Postgres-dialect SQL). Exactly one of `sql` or `query` must be provided.

    Pass organization_id to skip the Team→Organization lookup when org
    context is already available from the caller.
    """
    if sql and query:
        raise ValueError("Provide either sql or query, not both")
    if not sql and not query:
        raise ValueError("Provide either sql or query")

    hogql_pretty: str | None = None
    values: dict[str, object] = {}
    if query:
        sql, values, hogql_pretty = compile_hogql_to_ducklake_sql(team_id, query)

    assert sql is not None

    conninfo = make_duckgres_conninfo(team_id, organization_id=organization_id)
    with psycopg.connect(conninfo) as conn:
        _set_search_path(conn)
        with conn.cursor() as cur:
            cur.execute(sql, values or None)
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


def _calculate_table_size(conninfo: str, safe_schema: str, safe_table: str) -> int:
    try:
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.file_size_bytes
                    FROM ducklake_table_info('ducklake') t
                    JOIN __ducklake_metadata_ducklake.ducklake_schema s
                    ON t.schema_id = s.schema_id AND s.end_snapshot IS NULL
                    WHERE s.schema_name = %s AND t.table_name = %s
                    """,
                    (safe_schema, safe_table),
                )
                row = cur.fetchone()
                return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


def execute_ducklake_create_table(
    team_id: int,
    sql: str,
    schema_name: str,
    table_name: str,
    values: dict[str, object] | None = None,
    *,
    organization_id: str | None = None,
) -> DuckLakeTableResult:
    """Execute a query via duckgres and materialize the result as a DuckLake table.

    Creates or replaces a table in the given schema using CREATE OR REPLACE TABLE ... AS.
    The table is stored natively in DuckLake (Parquet on S3 + Postgres catalog metadata).

    Pass organization_id to skip the Team→Organization lookup when org
    context is already available from the caller.

    ``values`` carries parameter bindings for any ``%(name)s`` placeholders in ``sql``
    (as produced by ``compile_hogql_to_ducklake_sql``). It is passed through to
    ``psycopg`` so the SELECT body is executed with safe parameter binding.
    """
    safe_schema = sanitize_ducklake_identifier(schema_name, default_prefix="shadow")
    safe_table = sanitize_ducklake_identifier(table_name, default_prefix="model")
    qualified = psql.Identifier(safe_schema, safe_table)
    conninfo = make_duckgres_conninfo(team_id, organization_id=organization_id)
    # capture previous table size before replacing — best-effort, don't block materialization
    previous_file_size_bytes = _calculate_table_size(conninfo, safe_schema, safe_table)
    with psycopg.connect(conninfo) as conn:
        conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(safe_schema)))
        # duckgres SET seems to only accept a single comma-separated string value with single quotes
        _set_search_path(conn, extra_schemas=[safe_schema])
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("""
                    CREATE OR REPLACE TABLE {} AS (
                        {}
                    )
                """).format(qualified, psql.SQL(sql)),
                values or None,
            )
    row_count = 0
    try:
        with psycopg.connect(conninfo) as conn:
            _set_search_path(conn, extra_schemas=[safe_schema])
            with conn.cursor() as cur:
                cur.execute(psql.SQL("SELECT count(*) FROM {}").format(qualified))
                row = cur.fetchone()
                row_count = int(row[0]) if row else 0
    except Exception:
        pass
    # capture new table size — best-effort, don't block materialization
    file_size_bytes = _calculate_table_size(conninfo, safe_schema, safe_table)
    return DuckLakeTableResult(
        schema_name=safe_schema,
        table_name=safe_table,
        row_count=row_count,
        file_size_bytes=file_size_bytes,
        file_size_delta_bytes=file_size_bytes - previous_file_size_bytes,
    )
