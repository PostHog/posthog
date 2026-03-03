from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo

from posthog.ducklake.common import get_duckgres_config


@dataclass
class DuckLakeQueryResult:
    columns: list[str]
    types: list[str]
    results: list[list[Any]]


def execute_ducklake_query(team_id: int, sql: str) -> DuckLakeQueryResult:
    config = get_duckgres_config(team_id)
    conninfo = make_conninfo(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        sslmode="require",
    )
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [desc.name for desc in cur.description] if cur.description else []
            types = [str(desc.type_code) for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
    return DuckLakeQueryResult(columns=columns, types=types, results=[list(r) for r in rows])
