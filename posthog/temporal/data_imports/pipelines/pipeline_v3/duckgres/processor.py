from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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

DUCKGRES_APPLY_TABLE = "_posthog_source_batch_duckgres_apply"


@dataclass(frozen=True)
class DuckgresColumn:
    name: str
    type_sql: str


@dataclass(frozen=True)
class BatchApplyOperation:
    kind: Literal["replace", "create", "insert", "merge"]
    ensure_target_columns: bool = False
    primary_keys: list[str] | None = None


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

    _ensure_duckgres_apply_table(conn, duckgres_schema)
    if _has_duckgres_batch_applied(conn, duckgres_schema, batch=batch):
        logger.info(
            "duckgres_batch_already_applied",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            run_uuid=batch.run_uuid,
            batch_index=batch.batch_index,
        )
        return

    parquet_schema = _read_parquet_schema(conn, batch.s3_path)
    columns = [column.name for column in parquet_schema]
    operation = _plan_batch_operation(
        conn,
        batch,
        duckgres_schema=duckgres_schema,
        duckgres_table=duckgres_table,
    )

    if operation.kind == "replace":
        logger.info(
            "duckgres_replacing_table_from_batch",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            batch_index=batch.batch_index,
            table=duckgres_table,
        )

    with conn.transaction():
        if operation.ensure_target_columns:
            _ensure_target_columns(conn, duckgres_schema, duckgres_table, parquet_schema)
        _apply_batch_operation(
            conn,
            operation,
            duckgres_schema=duckgres_schema,
            duckgres_table=duckgres_table,
            s3_path=batch.s3_path,
            columns=columns,
        )
        _mark_duckgres_batch_applied(conn, duckgres_schema, batch=batch)
        return


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
    if batch.batch_index != 0 or batch.is_resume:
        return False
    if batch.sync_type == "full_refresh":
        return True
    if batch.sync_type == "incremental":
        return batch.is_first_ever_sync
    return False


def _plan_batch_operation(
    conn: psycopg.Connection[Any],
    batch: PendingBatch,
    *,
    duckgres_schema: str,
    duckgres_table: str,
) -> BatchApplyOperation:
    if _should_replace_table(batch):
        return BatchApplyOperation(kind="replace")

    if not _table_exists(conn, duckgres_schema, duckgres_table):
        return BatchApplyOperation(kind="create")

    if batch.sync_type == "incremental":
        if batch.is_first_ever_sync:
            return BatchApplyOperation(kind="insert", ensure_target_columns=True)

        primary_keys = _primary_keys(batch)
        if not primary_keys:
            raise ValueError("Duckgres incremental batches require primary keys")
        return BatchApplyOperation(kind="merge", ensure_target_columns=True, primary_keys=primary_keys)

    if batch.sync_type in ("full_refresh", "append"):
        return BatchApplyOperation(kind="insert", ensure_target_columns=True)

    raise ValueError(f"Unsupported Duckgres sync type: {batch.sync_type}")


def _table_exists(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str) -> bool:
    cursor = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
            AND table_name = %s
        LIMIT 1
        """,
        [duckgres_schema, duckgres_table],
    )
    return cursor.fetchone() is not None


def _replace_table(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str) -> None:
    conn.execute(
        sql.SQL("CREATE OR REPLACE TABLE {}.{} AS SELECT * FROM read_parquet(%s)").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _create_table_from_parquet(
    conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str
) -> None:
    conn.execute(
        sql.SQL("CREATE TABLE {}.{} AS SELECT * FROM read_parquet(%s)").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _ensure_duckgres_apply_table(conn: psycopg.Connection[Any], duckgres_schema: str) -> None:
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.{} (
                schema_id VARCHAR NOT NULL,
                run_uuid VARCHAR NOT NULL,
                batch_index BIGINT NOT NULL,
                batch_id VARCHAR NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (schema_id, run_uuid, batch_index)
            )
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        )
    )


def _has_duckgres_batch_applied(conn: psycopg.Connection[Any], duckgres_schema: str, *, batch: PendingBatch) -> bool:
    cursor = conn.execute(
        sql.SQL(
            """
            SELECT 1
            FROM {}.{}
            WHERE schema_id = %s
                AND run_uuid = %s
                AND batch_index = %s
            LIMIT 1
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        ),
        [batch.schema_id, batch.run_uuid, batch.batch_index],
    )
    return cursor.fetchone() is not None


def _mark_duckgres_batch_applied(conn: psycopg.Connection[Any], duckgres_schema: str, *, batch: PendingBatch) -> None:
    conn.execute(
        sql.SQL(
            """
            INSERT INTO {}.{} (schema_id, run_uuid, batch_index, batch_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (schema_id, run_uuid, batch_index) DO NOTHING
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        ),
        [batch.schema_id, batch.run_uuid, batch.batch_index, batch.id],
    )


def _read_parquet_columns(conn: psycopg.Connection[Any], s3_path: str) -> list[str]:
    return [column.name for column in _read_parquet_schema(conn, s3_path)]


def _read_parquet_schema(conn: psycopg.Connection[Any], s3_path: str) -> list[DuckgresColumn]:
    cursor = conn.execute("DESCRIBE SELECT * FROM read_parquet(%s) LIMIT 0", [s3_path])
    rows = cursor.fetchall()
    if not rows:
        raise ValueError("Duckgres could not read parquet column metadata")
    return [DuckgresColumn(name=str(row[0]), type_sql=str(row[1])) for row in rows]


def _ensure_target_columns(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    parquet_schema: list[DuckgresColumn],
) -> None:
    cursor = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
            AND table_name = %s
        """,
        [duckgres_schema, duckgres_table],
    )
    existing_columns = {str(row[0]) for row in cursor.fetchall()}

    for column in parquet_schema:
        if column.name in existing_columns:
            continue
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} ADD COLUMN {} {}").format(
                sql.Identifier(duckgres_schema),
                sql.Identifier(duckgres_table),
                sql.Identifier(column.name),
                sql.SQL(column.type_sql),
            )
        )


def _apply_batch_operation(
    conn: psycopg.Connection[Any],
    operation: BatchApplyOperation,
    *,
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
) -> None:
    if operation.kind == "replace":
        _replace_table(conn, duckgres_schema, duckgres_table, s3_path)
        return
    if operation.kind == "create":
        _create_table_from_parquet(conn, duckgres_schema, duckgres_table, s3_path)
        return
    if operation.kind == "insert":
        _insert_batch(conn, duckgres_schema, duckgres_table, s3_path, columns)
        return
    if operation.kind == "merge":
        if operation.primary_keys is None:
            raise ValueError("Duckgres merge operation requires primary keys")
        _merge_batch(conn, duckgres_schema, duckgres_table, s3_path, columns, operation.primary_keys)
        return
    raise ValueError(f"Unsupported Duckgres apply operation: {operation.kind}")


def _insert_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
) -> None:
    insert_columns = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    select_columns = sql.SQL(", ").join(sql.SQL("source.{}").format(sql.Identifier(column)) for column in columns)
    conn.execute(
        sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM read_parquet(%s) AS source").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
            insert_columns,
            select_columns,
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
