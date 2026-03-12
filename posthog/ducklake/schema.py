from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

import psycopg

from posthog.ducklake.client import _make_duckgres_conninfo

DUCKLAKE_SCHEMA_CACHE_TTL_SECONDS = 60 * 5


@dataclass(frozen=True)
class DuckLakeSchemaTable:
    schema_name: str
    table_name: str
    columns: list[tuple[str, str, bool]]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


def get_ducklake_schema_cache_key(team_id: int) -> str:
    return f"ducklake_schema:{team_id}"


def get_cached_ducklake_schema(team_id: int) -> list[DuckLakeSchemaTable]:
    cache_key = get_ducklake_schema_cache_key(team_id)
    cached_schema = cache.get(cache_key)
    if cached_schema is not None:
        return cached_schema

    schema = fetch_ducklake_schema(team_id)
    cache.set(cache_key, schema, DUCKLAKE_SCHEMA_CACHE_TTL_SECONDS)
    return schema


def fetch_ducklake_schema(team_id: int) -> list[DuckLakeSchemaTable]:
    conninfo = _make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        conn.execute("SET search_path TO 'posthog'")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    columns.table_schema,
                    columns.table_name,
                    columns.column_name,
                    pg_catalog.format_type(attributes.atttypid, attributes.atttypmod) AS data_type,
                    columns.is_nullable = 'YES' AS is_nullable
                FROM information_schema.columns AS columns
                INNER JOIN pg_catalog.pg_namespace AS namespaces
                    ON namespaces.nspname = columns.table_schema
                INNER JOIN pg_catalog.pg_class AS classes
                    ON classes.relname = columns.table_name
                    AND classes.relnamespace = namespaces.oid
                INNER JOIN pg_catalog.pg_attribute AS attributes
                    ON attributes.attrelid = classes.oid
                    AND attributes.attname = columns.column_name
                    AND attributes.attnum > 0
                    AND NOT attributes.attisdropped
                WHERE columns.table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY columns.table_schema, columns.table_name, columns.ordinal_position
                """
            )
            rows = cur.fetchall()

    tables: dict[tuple[str, str], list[tuple[str, str, bool]]] = {}
    for schema_name, table_name, column_name, data_type, is_nullable in rows:
        key = (str(schema_name), str(table_name))
        tables.setdefault(key, []).append((str(column_name), str(data_type), bool(is_nullable)))

    return [
        DuckLakeSchemaTable(schema_name=schema_name, table_name=table_name, columns=columns)
        for (schema_name, table_name), columns in tables.items()
    ]
