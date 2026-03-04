from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from posthog.ducklake.common import get_duckgres_config, sanitize_ducklake_identifier


@dataclass
class DuckLakeQueryResult:
    columns: list[str]
    types: list[str]
    results: list[list[Any]]


@dataclass
class DuckLakeTableResult:
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


def execute_ducklake_query(team_id: int, sql: str) -> DuckLakeQueryResult:
    conninfo = _make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc.name for desc in cur.description] if cur.description else []
            types = [str(desc.type_code) for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
    return DuckLakeQueryResult(columns=columns, types=types, results=[list(r) for r in rows])


def execute_ducklake_create_table(team_id: int, sql: str, table_name: str) -> DuckLakeTableResult:
    """Execute a query via duckgres and materialize the result as a DuckLake table.

    Creates or replaces a table in the public schema using CREATE OR REPLACE TABLE ... AS.
    The table is stored natively in DuckLake (Parquet on S3 + Postgres catalog metadata).
    """
    safe_table = sanitize_ducklake_identifier(table_name, default_prefix="model")

    conninfo = _make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(f"CREATE OR REPLACE TABLE public.{safe_table} AS {sql}")

            cur.execute(f"SELECT count(*) FROM public.{safe_table}")
            row = cur.fetchone()
            row_count = int(row[0]) if row else 0

    return DuckLakeTableResult(
        table_name=safe_table,
        row_count=row_count,
    )
