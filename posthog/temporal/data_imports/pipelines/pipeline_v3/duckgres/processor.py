from __future__ import annotations

from typing import Any

import psycopg
import structlog
from psycopg import sql

from posthog.ducklake.common import get_duckgres_config_for_org
from posthog.ducklake.storage import setup_duckgres_session
from posthog.models import Team
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import PendingBatch

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema

logger = structlog.get_logger(__name__)


def process_batch(batch: PendingBatch) -> None:
    job = ExternalDataJob.objects.select_related("schema", "schema__source").get(
        id=batch.job_id,
        team_id=batch.team_id,
    )
    schema = job.schema
    if schema is None:
        raise ValueError(f"ExternalDataJob {batch.job_id} has no schema")

    with _connect_to_duckgres(batch.team_id) as conn:
        setup_duckgres_session(conn)
        _process_batch(conn, batch, schema)


def _connect_to_duckgres(team_id: int) -> psycopg.Connection[Any]:
    team = Team.objects.only("organization_id").get(id=team_id)
    config = get_duckgres_config_for_org(str(team.organization_id))
    return psycopg.connect(
        host=config["DUCKGRES_HOST"],
        port=config["DUCKGRES_PORT"],
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        autocommit=True,
    )


def _process_batch(conn: psycopg.Connection[Any], batch: PendingBatch, schema: ExternalDataSchema) -> None:
    duckgres_schema = _duckgres_schema_name(batch.team_id)
    duckgres_table = _duckgres_table_name(schema)

    conn.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(duckgres_schema)),
    )

    if batch.sync_type == "cdc":
        raise ValueError("Duckgres batch sink does not support CDC batches yet")

    columns = _read_parquet_columns(conn, batch.s3_path)

    if _should_replace_table(batch):
        logger.info(
            "duckgres_replacing_table_from_batch",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            batch_index=batch.batch_index,
            table=duckgres_table,
        )
        conn.execute(
            sql.SQL("CREATE OR REPLACE TABLE {}.{} AS SELECT * FROM read_parquet(%s)").format(
                sql.Identifier(duckgres_schema),
                sql.Identifier(duckgres_table),
            ),
            [batch.s3_path],
        )
        return

    _ensure_table_exists(conn, duckgres_schema, duckgres_table, batch.s3_path)

    if batch.sync_type == "incremental":
        primary_keys = _primary_keys(batch)
        if not primary_keys:
            raise ValueError("Duckgres incremental batches require primary keys")
        _merge_batch(conn, duckgres_schema, duckgres_table, batch.s3_path, columns, primary_keys)
        return

    if batch.sync_type in ("full_refresh", "append"):
        _insert_batch(conn, duckgres_schema, duckgres_table, batch.s3_path)
        return

    raise ValueError(f"Unsupported Duckgres sync type: {batch.sync_type}")


def _duckgres_schema_name(team_id: int) -> str:
    return f"posthog_data_imports_team_{team_id}"


def _duckgres_table_name(schema: ExternalDataSchema) -> str:
    source_type = schema.source.source_type
    normalized_name = schema.normalized_name
    raw_name = (
        f"{source_type}_{schema.source.prefix}_{normalized_name}"
        if schema.source.prefix
        else f"{source_type}_{normalized_name}"
    )
    return NamingConvention.normalize_identifier(raw_name, max_length=63)


def _should_replace_table(batch: PendingBatch) -> bool:
    return batch.batch_index == 0 and not batch.is_resume and batch.sync_type in ("full_refresh", "incremental")


def _ensure_table_exists(
    conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str
) -> None:
    conn.execute(
        sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} AS SELECT * FROM read_parquet(%s) WHERE false").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _read_parquet_columns(conn: psycopg.Connection[Any], s3_path: str) -> list[str]:
    cursor = conn.execute("SELECT * FROM read_parquet(%s) LIMIT 0", [s3_path])
    description = cursor.description
    if not description:
        raise ValueError("Duckgres could not read parquet column metadata")
    return [column.name for column in description]


def _insert_batch(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str) -> None:
    conn.execute(
        sql.SQL("INSERT INTO {}.{} SELECT * FROM read_parquet(%s)").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _merge_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
    primary_keys: list[str],
) -> None:
    normalized_primary_keys = [NamingConvention.normalize_identifier(key) for key in primary_keys]
    missing_keys = [key for key in normalized_primary_keys if key not in columns]
    if missing_keys:
        raise ValueError(f"Duckgres incremental batch missing primary keys: {missing_keys}")

    update_columns = [column for column in columns if column not in normalized_primary_keys]
    if not update_columns:
        update_columns = [normalized_primary_keys[0]]
    on_clause = sql.SQL(" AND ").join(
        sql.SQL("source.{} = target.{}").format(sql.Identifier(key), sql.Identifier(key))
        for key in normalized_primary_keys
    )
    update_clause = sql.SQL(", ").join(
        sql.SQL("{} = source.{}").format(sql.Identifier(column), sql.Identifier(column)) for column in update_columns
    )
    insert_columns = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    insert_values = sql.SQL(", ").join(sql.SQL("source.{}").format(sql.Identifier(column)) for column in columns)

    matched_clause = sql.SQL("WHEN MATCHED THEN UPDATE SET {}").format(update_clause)

    query = sql.SQL(
        """
        MERGE INTO {}.{} AS target
        USING read_parquet(%s) AS source
        ON {}
        {}
        WHEN NOT MATCHED THEN INSERT ({}) VALUES ({})
        """
    ).format(
        sql.Identifier(duckgres_schema),
        sql.Identifier(duckgres_table),
        on_clause,
        matched_clause,
        insert_columns,
        insert_values,
    )
    conn.execute(query, [s3_path])


def _primary_keys(batch: PendingBatch) -> list[str]:
    raw = batch.metadata.get("primary_keys")
    if not isinstance(raw, list):
        return []
    return [str(key) for key in raw]
