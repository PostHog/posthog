from __future__ import annotations

from django.conf import settings

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg import sql as psql

from posthog.ducklake.client import make_duckgres_conninfo

_SYSTEM_SCHEMAS = frozenset(
    {
        "information_schema",
        "pg_catalog",
        "public",
        "system",
        "__ducklake_metadata_ducklake",
    }
)


def get_mwh_tables(team_id: int) -> list[dict[str, str]]:
    conninfo = make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            placeholders = psql.SQL(", ").join(psql.Placeholder() * len(_SYSTEM_SCHEMAS))
            query = psql.SQL("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema NOT IN ({})
                ORDER BY table_schema, table_name
            """).format(placeholders)
            cur.execute(query, list(_SYSTEM_SCHEMAS))
            return [{"schema": row[0], "table": row[1]} for row in cur.fetchall()]


def get_mwh_columns(team_id: int, schema_name: str, table_name: str) -> list[tuple[str, str, bool]]:
    conninfo = make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable = 'YES'
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema_name, table_name),
            )
            return [(row[0], row[1], row[2]) for row in cur.fetchall()]


def get_mwh_row_count(team_id: int, schema_name: str, table_name: str) -> int:
    conninfo = make_duckgres_conninfo(team_id)
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(psql.SQL("SELECT count(*) FROM {}").format(psql.Identifier(schema_name, table_name)))
            row = cur.fetchone()
            return int(row[0]) if row else 0


_PG_TO_ARROW: dict[str, pa.DataType] = {
    "integer": pa.int32(),
    "bigint": pa.int64(),
    "smallint": pa.int16(),
    "boolean": pa.bool_(),
    "real": pa.float32(),
    "double precision": pa.float64(),
    "numeric": pa.decimal128(38, 18),
    "timestamp": pa.timestamp("us"),
    "timestamp without time zone": pa.timestamp("us"),
    "timestamp with time zone": pa.timestamp("us", tz="UTC"),
    "date": pa.date32(),
    "time": pa.time64("us"),
    "text": pa.string(),
    "character varying": pa.string(),
    "varchar": pa.string(),
    "uuid": pa.string(),
    "json": pa.string(),
    "jsonb": pa.string(),
    "bytea": pa.binary(),
}


def _pg_type_to_arrow(pg_type: str) -> pa.DataType:
    return _PG_TO_ARROW.get(pg_type, pa.string())


def copy_mwh_table_to_s3(
    team_id: int,
    schema_name: str,
    table_name: str,
    s3_folder_path: str,
    normalized_table_name: str,
) -> str:
    from products.data_warehouse.backend.s3 import get_s3_client

    conninfo = make_duckgres_conninfo(team_id)
    s3_folder = f"{settings.BUCKET_URL}/{s3_folder_path}/{normalized_table_name}"
    s3_file = f"{s3_folder}/data.parquet"

    columns = get_mwh_columns(team_id, schema_name, table_name)
    arrow_fields = [pa.field(name, _pg_type_to_arrow(dtype), nullable=nullable) for name, dtype, nullable in columns]
    arrow_schema = pa.schema(arrow_fields)

    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(psql.SQL("SELECT * FROM {}").format(psql.Identifier(schema_name, table_name)))
            rows = cur.fetchall()

    table = pa.table(
        {field.name: [row[i] for row in rows] for i, field in enumerate(arrow_fields)}, schema=arrow_schema
    )

    s3 = get_s3_client()
    with s3.open(s3_file, "wb") as f:
        pq.write_table(table, f)

    return s3_folder
