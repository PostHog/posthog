"""Builders for the per-schema `schema_metadata` JSON.

Every SQL source persists a `schema_metadata` blob inside
`ExternalDataSchema.sync_type_config` so the column picker, direct-query
table builder, and per-row location routing don't need to re-query the
source on every read.

The shape was originally introduced for Postgres (in
`products/data_warehouse/backend/postgres_helpers.py`) but is fully
driver-agnostic — it just stores discovered columns, foreign keys, and
the source location triple. Hoisted here so MySQL / MSSQL / BigQuery /
Snowflake / Redshift can populate the same blob and the column picker
works for every SQL source without per-driver branches in the API.

JSON shape:

    {
        "columns": [{"name": ..., "data_type": ..., "is_nullable": ...}],
        "foreign_keys": [{"column": ..., "target_table": ..., "target_column": ...}],
        "source_catalog": ... | None,
        "source_schema": ... | None,
        "source_table_name": ... | None,
    }

`data_type` strings are driver-native (Postgres returns lowercase
`text`, BigQuery uppercase `STRING`, Snowflake uppercase `VARCHAR`,
ClickHouse mixed-case `Int64`). The picker only renders them as a
label; no consumer should branch on case.
"""

from __future__ import annotations

from typing import Any


def sql_schema_metadata(
    columns: list[tuple[str, str, bool]],
    foreign_keys: list[tuple[str, str, str]] | None = None,
    source_catalog: str | None = None,
    source_schema: str | None = None,
    source_table_name: str | None = None,
) -> dict[str, Any]:
    """Build the `schema_metadata` JSON for one schema row.

    Mirrors `postgres_schema_metadata` exactly so existing Postgres rows
    remain compatible; non-Postgres sources adopt the same shape on
    their next `refresh_schemas` run.
    """
    return {
        "columns": [
            {"name": column_name, "data_type": column_type, "is_nullable": nullable}
            for column_name, column_type, nullable in columns
        ],
        "foreign_keys": [
            {"column": column_name, "target_table": target_table, "target_column": target_column}
            for column_name, target_table, target_column in (foreign_keys or [])
        ],
        "source_catalog": source_catalog,
        "source_schema": source_schema,
        "source_table_name": source_table_name,
    }


def extract_available_column_names(schema_metadata: dict[str, Any] | None) -> set[str]:
    """Return the set of column names persisted on a `schema_metadata` row.

    Used by `prune_enabled_columns` to detect source-side column drops
    on every refresh.
    """
    if not isinstance(schema_metadata, dict):
        return set()
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return set()
    return {column["name"] for column in columns if isinstance(column, dict) and isinstance(column.get("name"), str)}
