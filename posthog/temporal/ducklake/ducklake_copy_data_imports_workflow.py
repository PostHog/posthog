import re
import json
import uuid
import typing
import datetime as dt
import dataclasses
from urllib.parse import urlparse

from django.conf import settings
from django.db import close_old_connections

import duckdb
import deltalake
from psycopg import sql as psql
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.ducklake.common import (
    _get_org_id_for_team,
    attach_catalog,
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    get_config,
    get_duckgres_server_by_team_org,
    get_duckgres_server_for_organization,
    is_dev_mode,
)
from posthog.ducklake.storage import (
    cleanup_staged_files,
    compute_staging_uri,
    configure_connection,
    connect_to_duckgres,
    create_staging_read_secret,
    ensure_ducklake_bucket_exists,
    get_deltalake_storage_options,
    setup_duckgres_session,
    stage_delta_table,
)
from posthog.ducklake.verification import (
    DuckLakeCopyVerificationParameter,
    DuckLakeCopyVerificationQuery,
    get_data_imports_verification_queries,
)
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ducklake.metrics import (
    get_ducklake_copy_data_imports_finished_metric,
    get_ducklake_copy_data_imports_verification_metric,
)

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.facade.pipelines import DUCKGRES_BATCH_SINK_FLAG, is_duckgres_sink_team_member

LOGGER = get_logger(__name__)
DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX = "data_imports"
DATA_IMPORTS_LANDING_PREFIX = "data_imports"


class _VerificationCursor(typing.Protocol):
    @property
    def description(self) -> typing.Sequence[object] | None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class _VerificationConnection(typing.Protocol):
    def execute(self, query: str, params: typing.Sequence[object] | None = None) -> _VerificationCursor: ...


@dataclasses.dataclass
class DuckLakeCopyWorkflowGateInputs:
    """Inputs for the DuckLake copy workflow gate activity."""

    team_id: int


@dataclasses.dataclass
class DataImportsDuckLakeCopyInputs:
    """Workflow inputs passed to DuckLakeCopyDataImportsWorkflow."""

    team_id: int
    job_id: str
    schema_ids: list[uuid.UUID]
    prepared_queryable_folders: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_ids": [str(sid) for sid in self.schema_ids],
            "prepared_queryable_folders": self.prepared_queryable_folders,
        }


@dataclasses.dataclass
class DuckLakeCopyDataImportsMetadata:
    """Metadata for a data imports schema to copy into DuckLake."""

    # General
    model_label: str

    # Source (Delta table)
    source_schema_id: str
    source_schema_name: str
    source_normalized_name: str
    source_table_uri: str

    # Destination (DuckLake)
    ducklake_schema_name: str
    ducklake_table_name: str

    # Source metadata (optional, with defaults)
    source_partition_column: str | None = None
    prepared_source_uri: str | None = None

    # Permanent object paths copied into the DuckLake-managed bucket.
    landing_uri: str | None = None

    # Staging (duckgres path)
    staging_uri: str | None = None

    # Verification
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DuckLakeCopyDataImportsActivityInputs:
    """Inputs for a single model copy activity."""

    team_id: int
    job_id: str
    model: DuckLakeCopyDataImportsMetadata


@dataclasses.dataclass
class DuckLakeCopyDataImportsVerificationResult:
    """Result of a single verification check for data imports DuckLake copy."""

    name: str
    passed: bool
    observed_value: float | None = None
    expected_value: float | None = None
    tolerance: float | None = None
    description: str | None = None
    sql: str | None = None
    error: str | None = None


@activity.defn
async def ducklake_copy_data_imports_gate_activity(inputs: DuckLakeCopyWorkflowGateInputs) -> bool:
    """Evaluate whether the DuckLake data imports copy workflow should run for a team.

    The mutual exclusion with the Duckgres v3 batch sink is per-source and lives in
    prepare_data_imports_ducklake_metadata_activity (v3 sources the sink owns are
    dropped there), not here: the sink only follows a team's v3 sources, so a
    sink-enabled team can still have non-v3 sources that this workflow must copy.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports gate")
        return False

    try:
        return feature_enabled_or_false(
            "ducklake-data-imports-copy-workflow",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        await logger.awarning(
            "Failed to evaluate DuckLake data imports feature flag",
            error=str(error),
        )
        capture_exception(error)
        return False


@activity.defn
async def prepare_data_imports_ducklake_metadata_activity(
    inputs: DataImportsDuckLakeCopyInputs,
) -> list[DuckLakeCopyDataImportsMetadata]:
    """Resolve data imports schemas referenced in the workflow inputs into copy-ready metadata."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    if not inputs.schema_ids:
        await logger.ainfo("DuckLake copy requested but no schema_ids were provided - skipping")
        return []

    # Resolve the same per-team schema the v3 sink uses (table_suffix-aware), so the
    # historical copy and the live sink never diverge on schema name. All schemas in the
    # batch belong to one team, so this is loop-invariant — resolve it once.
    ducklake_schema_name = await database_sync_to_async(duckgres_data_imports_schema)(inputs.team_id)

    # Per-source mutual exclusion with the Duckgres v3 batch sink. The sink owns a
    # registered team's v3 sources (it mirrors them live + backfills history), so
    # drop those here; non-v3 sources stay on the copy workflow because the sink never
    # touches them. A flagged team without a DuckgresServerTeam membership remains
    # on this copy path until it completes the enable flow.
    # is_pipeline_v3_enabled is the same gate the v3 router uses, so "copy" and
    # "sink" never disagree on who owns a source (and both fail to "copy owns it").
    # Lazy import: create_job_model pulls in temporalio.activity + the data_warehouse
    # facade, which we don't want on this module's import path.
    from products.warehouse_sources.backend.facade.pipelines import (  # noqa: PLC0415 — keeps the heavy temporal/facade deps off the import path
        is_pipeline_v3_enabled,
    )

    sink_enabled = is_dev_mode()
    try:
        gate_team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
        if not sink_enabled and await database_sync_to_async(is_duckgres_sink_team_member)(inputs.team_id):
            sink_enabled = feature_enabled_or_false(
                DUCKGRES_BATCH_SINK_FLAG,
                str(gate_team.uuid),
                groups={"organization": str(gate_team.organization_id), "project": str(gate_team.id)},
                send_feature_flag_events=False,
            )
    except Exception as error:
        await logger.awarning("Failed to resolve duckgres batch sink ownership; copying all schemas", error=str(error))
        capture_exception(error)
    sink_owns_source_type: dict[str, bool] = {}

    model_list: list[DuckLakeCopyDataImportsMetadata] = []

    for schema_id in inputs.schema_ids:
        schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("team", "table", "source").get)(
            id=schema_id, team_id=inputs.team_id
        )

        normalized_name = schema.normalized_name
        source_type = schema.source.source_type

        if sink_enabled:
            if source_type not in sink_owns_source_type:
                sink_owns_source_type[source_type] = await database_sync_to_async(is_pipeline_v3_enabled)(
                    inputs.team_id, source_type
                )
            if sink_owns_source_type[source_type]:
                await logger.ainfo(
                    "Skipping schema owned by the duckgres batch sink (v3 source)",
                    schema_id=str(schema.id),
                    source_type=source_type,
                )
                continue
        source_table_uri = _data_imports_source_table_uri(schema)
        prepared_queryable_folder = inputs.prepared_queryable_folders.get(str(schema.id))
        prepared_source_uri = None
        landing_uri = None
        staging_uri = None
        if prepared_queryable_folder:
            prepared_source_uri = _data_imports_prepared_source_uri(schema, prepared_queryable_folder)
            landing_uri = await database_sync_to_async(_resolve_data_imports_landing_uri)(
                team_id=inputs.team_id,
                schema_id=str(schema.id),
                job_id=inputs.job_id,
            )
        else:
            staging_uri = await database_sync_to_async(_resolve_data_imports_staging_uri)(
                source_table_uri, team_id=inputs.team_id
            )

        # Get partition column from Delta metadata (source of truth)
        partition_column = await database_sync_to_async(_detect_data_imports_partition_column)(
            source_table_uri, team_id=inputs.team_id
        )

        model_list.append(
            DuckLakeCopyDataImportsMetadata(
                model_label=f"{source_type}_{normalized_name}",
                source_schema_id=str(schema.id),
                source_schema_name=schema.name,
                source_normalized_name=normalized_name,
                source_table_uri=source_table_uri,
                ducklake_schema_name=ducklake_schema_name,
                ducklake_table_name=duckgres_data_imports_table_name(schema),
                verification_queries=list(get_data_imports_verification_queries(normalized_name)),
                source_partition_column=partition_column,
                prepared_source_uri=prepared_source_uri,
                landing_uri=landing_uri,
                staging_uri=staging_uri,
            )
        )

    return model_list


@activity.defn
def copy_data_imports_to_ducklake_activity(inputs: DuckLakeCopyDataImportsActivityInputs) -> bool:
    """Copy a single data imports schema's Delta snapshot into DuckLake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)
    # This activity runs in a long-lived worker thread that never goes through Django's
    # request/response cycle, so a connection killed by the DB/proxy (e.g. after
    # CONN_MAX_AGE) is never detected and closed before reuse.
    if not settings.TEST:
        close_old_connections()

    heartbeater = HeartbeaterSync(details=("ducklake_copy", inputs.model.model_label), logger=logger)
    with heartbeater:
        if is_dev_mode():
            return _copy_data_imports_via_duckdb(inputs, logger)
        return _copy_data_imports_via_duckgres(inputs, logger)


def _copy_data_imports_via_duckdb(inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any) -> bool:
    """Create the DuckLake table directly from Delta using the local DuckDB client."""
    if inputs.model.prepared_source_uri and inputs.model.landing_uri:
        return _copy_prepared_data_imports_via_duckdb(inputs, logger)

    alias = "ducklake"
    with duckdb.connect() as conn:
        config = get_config()
        configure_connection(conn)
        ensure_ducklake_bucket_exists(config=config, team_id=inputs.team_id)
        _attach_ducklake_catalog(conn, config, alias=alias)

        qualified_schema = f"{alias}.{inputs.model.ducklake_schema_name}"
        qualified_table = f"{qualified_schema}.{inputs.model.ducklake_table_name}"

        logger.info(
            "Creating DuckLake table from Delta snapshot",
            ducklake_table=qualified_table,
            source_table=inputs.model.source_table_uri,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {qualified_schema}")
        conn.execute(
            f"CREATE OR REPLACE TABLE {qualified_table} AS SELECT * FROM delta_scan(?)",
            [inputs.model.source_table_uri],
        )
        logger.info("Successfully materialized DuckLake table", ducklake_table=qualified_table)
    return True


def _copy_data_imports_via_duckgres(inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any) -> bool:
    """Stage Delta files and create the DuckLake table via duckgres."""
    org_id = _get_org_id_for_team(inputs.team_id)
    server = get_duckgres_server_for_organization(org_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {inputs.team_id}", non_retryable=True)
    bucket = server.bucket
    if not bucket:
        raise ApplicationError(f"No S3 bucket configured for team {inputs.team_id}", non_retryable=True)
    if inputs.model.prepared_source_uri and inputs.model.landing_uri:
        return _copy_prepared_data_imports_via_duckgres(inputs, logger, server)
    if not inputs.model.staging_uri:
        raise ApplicationError(f"No staging_uri for model {inputs.model.model_label}", non_retryable=True)

    logger.info(
        "Staging Delta files for duckgres",
        source_uri=inputs.model.source_table_uri,
        staging_uri=inputs.model.staging_uri,
    )
    stage_delta_table(
        source_uri=inputs.model.source_table_uri,
        catalog_bucket=bucket,
        organization_id=org_id,
    )

    schema = inputs.model.ducklake_schema_name
    table = f"{schema}.{inputs.model.ducklake_table_name}"

    with connect_to_duckgres(server) as conn:
        setup_duckgres_session(conn)
        create_staging_read_secret(conn, bucket)
        logger.info(
            "Creating DuckLake table from staged Delta snapshot via duckgres",
            ducklake_table=table,
            staging_uri=inputs.model.staging_uri,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM delta_scan(%s)",
            [inputs.model.staging_uri],
        )
        logger.info("Successfully materialized DuckLake table via duckgres", ducklake_table=table)
    return True


def _copy_prepared_parquet_files(source_uri: str, landing_uri: str) -> list[str]:
    """Copy prepared Parquet objects byte-for-byte, preserving their relative keys."""
    source_prefix = source_uri.removeprefix("s3://").rstrip("/")
    landing_prefix = landing_uri.removeprefix("s3://").rstrip("/")
    s3 = get_s3_client()
    found = s3.find(source_prefix)
    source_paths = list(found.keys()) if isinstance(found, dict) else list(found)
    parquet_paths = sorted(path for path in source_paths if str(path).lower().endswith(".parquet"))
    if not parquet_paths:
        raise ApplicationError(f"No prepared Parquet files found under {source_uri}", non_retryable=True)

    landing_paths: list[str] = []
    for source_path_value in parquet_paths:
        source_path = str(source_path_value).removeprefix("s3://")
        relative_path = source_path.removeprefix(f"{source_prefix}/")
        if relative_path == source_path or relative_path.startswith("../"):
            raise ApplicationError(f"Prepared file escaped source prefix: {source_path}", non_retryable=True)
        landing_path = f"{landing_prefix}/{relative_path}"
        s3.copy(source_path, landing_path)
        landing_paths.append(f"s3://{landing_path}")

    return landing_paths


def _data_imports_shadow_table_name(inputs: DuckLakeCopyDataImportsActivityInputs) -> str:
    schema_fragment = re.sub(r"[^A-Za-z0-9]", "", inputs.model.source_schema_id)[:8]
    job_fragment = re.sub(r"[^A-Za-z0-9]", "", inputs.job_id)[:8]
    return f"__ph_copy_{schema_fragment}_{job_fragment}"


def _prepared_generation_is_current(inputs: DuckLakeCopyDataImportsActivityInputs) -> bool:
    if not inputs.model.prepared_source_uri:
        return False
    try:
        schema = ExternalDataSchema.objects.select_related("table").get(
            id=inputs.model.source_schema_id,
            team_id=inputs.team_id,
        )
    except ExternalDataSchema.DoesNotExist:
        return False
    return (
        schema.table is not None
        and schema.table.queryable_folder == inputs.model.prepared_source_uri.rsplit("/", 1)[-1]
    )


def _copy_prepared_data_imports_via_duckdb(inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any) -> bool:
    alias = "ducklake"
    assert inputs.model.prepared_source_uri is not None
    assert inputs.model.landing_uri is not None
    landing_paths = _copy_prepared_parquet_files(inputs.model.prepared_source_uri, inputs.model.landing_uri)
    if not _prepared_generation_is_current(inputs):
        logger.info("Skipping stale prepared Parquet generation", prepared_source_uri=inputs.model.prepared_source_uri)
        return False

    with duckdb.connect() as conn:
        config = get_config()
        configure_connection(conn)
        ensure_ducklake_bucket_exists(config=config, team_id=inputs.team_id)
        _attach_ducklake_catalog(conn, config, alias=alias)

        schema = f"{alias}.{inputs.model.ducklake_schema_name}"
        live_table = f"{schema}.{inputs.model.ducklake_table_name}"
        shadow_name = _data_imports_shadow_table_name(inputs)
        shadow_table = f"{schema}.{shadow_name}"
        conn.execute("BEGIN")
        try:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(f"DROP TABLE IF EXISTS {shadow_table}")
            conn.execute(
                f"CREATE TABLE {shadow_table} AS "
                "SELECT * FROM read_parquet(?, union_by_name=true, hive_partitioning=true) LIMIT 0",
                [landing_paths],
            )
            if inputs.model.source_partition_column:
                conn.execute(
                    f"ALTER TABLE {shadow_table} SET PARTITIONED BY "
                    f"({_quote_identifier(inputs.model.source_partition_column)})"
                )
            for landing_path in landing_paths:
                conn.execute(
                    f"CALL ducklake_add_data_files('{alias}', ?, ?, schema => ?, "
                    "allow_missing => true, hive_partitioning => true)",
                    [shadow_name, landing_path, inputs.model.ducklake_schema_name],
                )
            conn.execute(f"DROP TABLE IF EXISTS {live_table}")
            conn.execute(f"ALTER TABLE {shadow_table} RENAME TO {_quote_identifier(inputs.model.ducklake_table_name)}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    logger.info(
        "Copied and registered prepared Parquet files in DuckLake",
        ducklake_table=live_table,
        file_count=len(landing_paths),
        landing_uri=inputs.model.landing_uri,
    )
    return True


def _copy_prepared_data_imports_via_duckgres(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any, server: typing.Any
) -> bool:
    assert inputs.model.prepared_source_uri is not None
    assert inputs.model.landing_uri is not None
    landing_paths = _copy_prepared_parquet_files(inputs.model.prepared_source_uri, inputs.model.landing_uri)
    if not _prepared_generation_is_current(inputs):
        logger.info("Skipping stale prepared Parquet generation", prepared_source_uri=inputs.model.prepared_source_uri)
        return False
    schema_name = inputs.model.ducklake_schema_name
    table_name = inputs.model.ducklake_table_name
    shadow_name = _data_imports_shadow_table_name(inputs)
    parquet_paths = psql.SQL("[{}]").format(psql.SQL(", ").join(psql.Literal(path) for path in landing_paths))

    with connect_to_duckgres(server) as conn:
        setup_duckgres_session(conn, extensions=("ducklake", "httpfs"))
        with conn.transaction():
            conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(schema_name)))
            conn.execute(
                psql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                    psql.Identifier(schema_name), psql.Identifier(shadow_name)
                )
            )
            conn.execute(
                psql.SQL(
                    "CREATE TABLE {}.{} AS SELECT * FROM "
                    "read_parquet({}, union_by_name=true, hive_partitioning=true) LIMIT 0"
                ).format(
                    psql.Identifier(schema_name),
                    psql.Identifier(shadow_name),
                    parquet_paths,
                )
            )
            if inputs.model.source_partition_column:
                conn.execute(
                    psql.SQL("ALTER TABLE {}.{} SET PARTITIONED BY ({})").format(
                        psql.Identifier(schema_name),
                        psql.Identifier(shadow_name),
                        psql.Identifier(inputs.model.source_partition_column),
                    )
                )
            for landing_path in landing_paths:
                conn.execute(
                    psql.SQL(
                        "CALL ducklake_add_data_files({}, {}, {}, schema => {}, "
                        "allow_missing => true, hive_partitioning => true)"
                    ).format(
                        psql.Literal("ducklake"),
                        psql.Literal(shadow_name),
                        psql.Literal(landing_path),
                        psql.Literal(schema_name),
                    )
                )
            conn.execute(
                psql.SQL("DROP TABLE IF EXISTS {}.{}").format(psql.Identifier(schema_name), psql.Identifier(table_name))
            )
            conn.execute(
                psql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                    psql.Identifier(schema_name),
                    psql.Identifier(shadow_name),
                    psql.Identifier(table_name),
                )
            )

    logger.info(
        "Copied and registered prepared Parquet files in DuckLake",
        ducklake_table=f"{schema_name}.{table_name}",
        file_count=len(landing_paths),
        landing_uri=inputs.model.landing_uri,
    )
    return True


@dataclasses.dataclass
class DuckLakeDataImportsStagingCleanupInputs:
    team_id: int
    staging_uri: str


@activity.defn
def cleanup_data_imports_staging_activity(inputs: DuckLakeDataImportsStagingCleanupInputs) -> None:
    """Clean up staged Delta files after successful verification."""
    bind_contextvars(team_id=inputs.team_id)
    # Same long-lived worker thread caveat as copy_data_imports_to_ducklake_activity.
    if not settings.TEST:
        close_old_connections()
    server = get_duckgres_server_by_team_org(inputs.team_id)
    if server is None:
        return
    cleanup_staged_files(
        staging_uri=inputs.staging_uri,
    )


def _data_imports_source_table_uri(schema: ExternalDataSchema) -> str:
    """S3 URI of the schema's Delta table, matching the folder the loader actually wrote.

    Uses ``normalized_s3_folder_name`` (the resolved folder leaf), which diverges from
    ``normalized_name`` for folder-pinned sources (e.g. Postgres ``public.users`` → folder
    ``users``). Reading ``normalized_name`` here points at a prefix with no ``_delta_log``
    and surfaces as "No files in log segment".
    """
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{schema.normalized_s3_folder_name}"


def _data_imports_prepared_source_uri(schema: ExternalDataSchema, queryable_folder: str) -> str:
    """Resolve the exact prepared Parquet generation produced by this import job."""
    if not queryable_folder or "/" in queryable_folder or queryable_folder in {".", ".."}:
        raise ApplicationError(f"Invalid prepared queryable folder '{queryable_folder}'", non_retryable=True)
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{queryable_folder}"


def _resolve_data_imports_landing_uri(*, team_id: int, schema_id: str, job_id: str) -> str:
    """Return a permanent, import-generation-specific prefix in the DuckLake bucket."""
    if is_dev_mode():
        bucket = get_config().get("DUCKLAKE_BUCKET")
    else:
        server = get_duckgres_server_by_team_org(team_id)
        bucket = server.bucket if server is not None else None
    if not bucket:
        raise ApplicationError(f"No S3 bucket configured for team {team_id}", non_retryable=True)

    safe_job_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job_id))
    return f"s3://{bucket}/{DATA_IMPORTS_LANDING_PREFIX}/{team_id}/{schema_id}/{safe_job_id}"


def _resolve_data_imports_staging_uri(source_uri: str, *, team_id: int) -> str | None:
    """Return the staged Delta URI required by prod duckgres, or None for local dev."""
    if is_dev_mode():
        return None

    server = get_duckgres_server_by_team_org(team_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {team_id}", non_retryable=True)
    if not server.bucket:
        raise ApplicationError(f"No S3 bucket configured for team {team_id}", non_retryable=True)

    return compute_staging_uri(source_uri, server.bucket)


def _detect_data_imports_partition_column(table_uri: str, *, team_id: int) -> str | None:
    """Detect partition column from Delta metadata (source of truth)."""
    if not table_uri:
        return None
    partition_columns = _fetch_delta_partition_columns(table_uri, team_id=team_id)
    return partition_columns[0] if partition_columns else None


def _fetch_delta_partition_columns(table_uri: str, *, team_id: int) -> list[str]:
    """Fetch partition columns from Delta table metadata."""
    options = get_deltalake_storage_options(team_id=team_id)
    try:
        delta_table = deltalake.DeltaTable(table_uri=table_uri, storage_options=options)
    except Exception as exc:
        LOGGER.bind(table_uri=table_uri).debug("Delta partition detection failed to open table", error=str(exc))
        return []

    try:
        metadata = delta_table.metadata()
    except Exception as exc:
        LOGGER.bind(table_uri=table_uri).debug("Delta partition detection failed to read metadata", error=str(exc))
        return []

    partition_columns = getattr(metadata, "partition_columns", None) or []
    return [column for column in partition_columns if column]


def _attach_ducklake_catalog(conn: duckdb.DuckDBPyConnection, config: dict[str, str], alias: str) -> None:
    """Attach the DuckLake catalog, swallowing the error if already attached."""
    try:
        attach_catalog(conn, config, alias=alias)
    except duckdb.CatalogException as exc:
        if alias not in str(exc):
            raise


@activity.defn
def verify_data_imports_ducklake_copy_activity(
    inputs: DuckLakeCopyDataImportsActivityInputs,
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    """Run configured verification queries to ensure the copy matches the source."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)
    # Same long-lived worker thread caveat as copy_data_imports_to_ducklake_activity.
    if not settings.TEST:
        close_old_connections()

    if not inputs.model.verification_queries:
        logger.info("No DuckLake verification queries configured - skipping")
        return []

    heartbeater = HeartbeaterSync(details=("ducklake_verify", inputs.model.model_label), logger=logger)
    with heartbeater:
        if is_dev_mode():
            results = _verify_data_imports_ducklake_copy_via_duckdb(inputs, logger)
        else:
            results = _verify_data_imports_ducklake_copy_via_duckgres(inputs, logger)

    failed = [result for result in results if not result.passed]
    if failed:
        logger.warning(
            "DuckLake verification checks failed",
            model_label=inputs.model.model_label,
            failures=[dataclasses.asdict(result) for result in failed],
        )

    return results


def _verify_data_imports_ducklake_copy_via_duckdb(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    alias = "ducklake"
    config = get_config()

    with duckdb.connect() as conn:
        configure_connection(conn)
        _attach_ducklake_catalog(conn, config, alias=alias)

        ducklake_table = f"{alias}.{inputs.model.ducklake_schema_name}.{inputs.model.ducklake_table_name}"
        format_values = _get_data_imports_verification_format_values(
            ducklake_table=ducklake_table,
            ducklake_schema=f"{alias}.{inputs.model.ducklake_schema_name}",
            ducklake_alias=alias,
            inputs=inputs,
        )
        return _run_data_imports_verification_checks(
            conn,
            inputs,
            ducklake_table,
            format_values,
            source_uri=_data_imports_verification_source_uri(inputs.model),
            parameter_placeholder="?",
            source_is_parquet=inputs.model.landing_uri is not None,
            logger=logger,
        )


def _verify_data_imports_ducklake_copy_via_duckgres(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    org_id = _get_org_id_for_team(inputs.team_id)
    server = get_duckgres_server_for_organization(org_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {inputs.team_id}", non_retryable=True)
    if not inputs.model.staging_uri and not inputs.model.landing_uri:
        raise ApplicationError(f"No staging_uri for model {inputs.model.model_label}", non_retryable=True)

    ducklake_table = f"{inputs.model.ducklake_schema_name}.{inputs.model.ducklake_table_name}"
    format_values = _get_data_imports_verification_format_values(
        ducklake_table=ducklake_table,
        ducklake_schema=inputs.model.ducklake_schema_name,
        ducklake_alias="",
        inputs=inputs,
    )

    with connect_to_duckgres(server) as conn:
        source_is_parquet = inputs.model.landing_uri is not None
        if source_is_parquet:
            setup_duckgres_session(conn, extensions=("ducklake", "httpfs"))
        else:
            setup_duckgres_session(conn)
        if inputs.model.staging_uri:
            create_staging_read_secret(conn, urlparse(inputs.model.staging_uri).netloc)
        return _run_data_imports_verification_checks(
            conn,
            inputs,
            ducklake_table,
            format_values,
            source_uri=_data_imports_verification_source_uri(inputs.model),
            parameter_placeholder="%s",
            source_is_parquet=source_is_parquet,
            logger=logger,
        )


def _data_imports_verification_source_uri(model: DuckLakeCopyDataImportsMetadata) -> str:
    if model.landing_uri:
        return f"{model.landing_uri.rstrip('/')}/**/*.parquet"
    return model.staging_uri or model.source_table_uri


def _get_data_imports_verification_format_values(
    *,
    ducklake_table: str,
    ducklake_schema: str,
    ducklake_alias: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
) -> dict[str, str]:
    return {
        "ducklake_table": ducklake_table,
        "ducklake_schema": ducklake_schema,
        "ducklake_alias": ducklake_alias,
        "schema_name": inputs.model.ducklake_schema_name,
        "table_name": inputs.model.ducklake_table_name,
    }


def _run_data_imports_verification_checks(
    conn: _VerificationConnection,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    ducklake_table: str,
    format_values: dict[str, str],
    *,
    source_uri: str,
    parameter_placeholder: str,
    source_is_parquet: bool,
    logger: typing.Any,
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    results: list[DuckLakeCopyDataImportsVerificationResult] = []

    for query in inputs.model.verification_queries:
        rendered_sql = query.sql.format(**format_values)
        if source_is_parquet:
            rendered_sql = rendered_sql.replace(
                "delta_scan(?)", "read_parquet(?, union_by_name=true, hive_partitioning=true)"
            )
        if parameter_placeholder != "?":
            rendered_sql = _replace_duckdb_parameter_placeholders(rendered_sql, parameter_placeholder)
        params = [
            _resolve_data_imports_verification_parameter(param, inputs, source_uri_override=source_uri)
            for param in query.parameters
        ]

        try:
            row = conn.execute(rendered_sql, params).fetchone()
        except Exception as exc:
            logger.warning(
                "DuckLake verification query failed",
                check=query.name,
                error=str(exc),
            )
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error=str(exc),
                )
            )
            continue

        if not row:
            logger.warning("DuckLake verification query returned no rows", check=query.name)
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error="Query returned no rows",
                )
            )
            continue

        raw_value = typing.cast(str | bytes | int | float, row[0])
        try:
            observed = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "DuckLake verification query returned a non-numeric value",
                check=query.name,
                value=raw_value,
            )
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error="Query did not return a numeric value",
                )
            )
            continue

        diff = abs(observed - (query.expected_value or 0.0))
        tolerance = query.tolerance or 0.0
        passed = diff <= tolerance
        log_method = logger.info if passed else logger.warning
        log_method(
            "DuckLake verification result",
            check=query.name,
            observed_value=observed,
            expected_value=query.expected_value,
            tolerance=tolerance,
        )

        results.append(
            DuckLakeCopyDataImportsVerificationResult(
                name=query.name,
                passed=passed,
                observed_value=observed,
                expected_value=query.expected_value,
                tolerance=tolerance,
                description=query.description,
                sql=rendered_sql,
            )
        )

    schema_result = _run_data_imports_schema_verification(
        conn,
        ducklake_table,
        inputs,
        source_uri_override=source_uri,
        parameter_placeholder=parameter_placeholder,
        source_is_parquet=source_is_parquet,
    )
    if schema_result:
        results.append(schema_result)

    partition_result = _run_data_imports_partition_verification(
        conn,
        ducklake_table,
        inputs,
        source_uri_override=source_uri,
        parameter_placeholder=parameter_placeholder,
        source_is_parquet=source_is_parquet,
    )
    if partition_result:
        results.append(partition_result)

    return results


def _replace_duckdb_parameter_placeholders(sql: str, placeholder: str) -> str:
    return sql.replace("?", placeholder)


def _resolve_data_imports_verification_parameter(
    parameter: DuckLakeCopyVerificationParameter,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
) -> str | int:
    """Resolve a verification parameter to its runtime value."""
    model = inputs.model
    mapping: dict[DuckLakeCopyVerificationParameter, str | int] = {
        DuckLakeCopyVerificationParameter.TEAM_ID: inputs.team_id,
        DuckLakeCopyVerificationParameter.JOB_ID: inputs.job_id,
        DuckLakeCopyVerificationParameter.MODEL_LABEL: model.model_label,
        DuckLakeCopyVerificationParameter.NORMALIZED_NAME: model.source_normalized_name,
        DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI: source_uri_override or model.source_table_uri,
        DuckLakeCopyVerificationParameter.SCHEMA_NAME: model.ducklake_schema_name,
        DuckLakeCopyVerificationParameter.TABLE_NAME: model.ducklake_table_name,
    }

    if parameter not in mapping:
        raise ValueError(f"Unsupported DuckLake verification parameter '{parameter}'")

    return mapping[parameter]


def _run_data_imports_schema_verification(
    conn: _VerificationConnection,
    ducklake_table: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
    parameter_placeholder: str = "?",
    source_is_parquet: bool = False,
) -> DuckLakeCopyDataImportsVerificationResult | None:
    """Compare schema between the copied source files and DuckLake table."""
    effective_source_uri = source_uri_override or inputs.model.source_table_uri
    try:
        source_schema = _fetch_source_schema(
            conn,
            effective_source_uri,
            parameter_placeholder=parameter_placeholder,
            source_is_parquet=source_is_parquet,
        )
        ducklake_schema = _fetch_schema(conn, ducklake_table)
    except Exception as exc:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.schema_hash",
            passed=False,
            description="Compare schema hash between Delta source and DuckLake table.",
            error=str(exc),
        )

    mismatches = _diff_schema(source_schema, ducklake_schema)
    passed = not mismatches
    error = None
    if not passed:
        preview = "; ".join(mismatches[:5])
        if len(mismatches) > 5:
            preview = f"{preview}; +{len(mismatches) - 5} more differences"
        error = f"Schema mismatch: {preview}"

    return DuckLakeCopyDataImportsVerificationResult(
        name="data_imports.schema_hash",
        passed=passed,
        description="Compare schema hash between Delta source and DuckLake table.",
        expected_value=0.0,
        observed_value=0.0 if passed else 1.0,
        tolerance=0.0,
        error=error,
    )


def _run_data_imports_partition_verification(
    conn: _VerificationConnection,
    ducklake_table: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
    parameter_placeholder: str = "?",
    source_is_parquet: bool = False,
) -> DuckLakeCopyDataImportsVerificationResult | None:
    """Verify partition counts match between source and DuckLake."""
    effective_source_uri = source_uri_override or inputs.model.source_table_uri
    partition_column = inputs.model.source_partition_column
    if not partition_column:
        return None

    # Get partition column type from Delta schema directly
    source_schema = _fetch_source_schema(
        conn,
        effective_source_uri,
        parameter_placeholder=parameter_placeholder,
        source_is_parquet=source_is_parquet,
    )
    partition_column_type = _get_column_type_from_schema(source_schema, partition_column)
    if partition_column_type is None:
        # Partition column doesn't exist in Delta schema - skip verification
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=f"Partition column '{partition_column}' not found in Delta schema",
        )

    bucket_expr = _build_partition_bucket_expression(partition_column, partition_column_type)
    source_scan = (
        f"read_parquet({parameter_placeholder}, union_by_name=true, hive_partitioning=true)"
        if source_is_parquet
        else f"delta_scan({parameter_placeholder})"
    )
    sql = f"""
        WITH source AS (
            SELECT {bucket_expr} AS bucket, count(*) AS cnt
            FROM {source_scan}
            GROUP BY 1
        ),
        ducklake AS (
            SELECT {bucket_expr} AS bucket, count(*) AS cnt
            FROM {ducklake_table}
            GROUP BY 1
        )
        SELECT COALESCE(source.bucket, ducklake.bucket) AS bucket,
               COALESCE(source.cnt, 0) AS source_count,
               COALESCE(ducklake.cnt, 0) AS ducklake_count
        FROM source
        FULL OUTER JOIN ducklake USING (bucket)
        WHERE COALESCE(source.cnt, 0) != COALESCE(ducklake.cnt, 0)
        ORDER BY bucket
    """

    try:
        mismatches = conn.execute(sql, [effective_source_uri]).fetchall()
    except Exception as exc:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=str(exc),
        )

    if mismatches:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            expected_value=0.0,
            observed_value=float(len(mismatches)),
            tolerance=0.0,
            error=f"Partition mismatches detected: {mismatches[:5]}",
        )

    return DuckLakeCopyDataImportsVerificationResult(
        name="data_imports.partition_counts",
        passed=True,
        description="Ensure partition counts match between source and DuckLake.",
        expected_value=0.0,
        observed_value=0.0,
        tolerance=0.0,
    )


def _fetch_delta_schema(
    conn: _VerificationConnection, source_uri: str, *, parameter_placeholder: str = "?"
) -> list[tuple[str, str]]:
    """Fetch schema from a Delta table."""
    cursor = conn.execute(
        f"SELECT * FROM delta_scan({parameter_placeholder}) LIMIT 0",
        [source_uri],
    )
    return _schema_from_cursor_description(cursor)


def _fetch_source_schema(
    conn: _VerificationConnection,
    source_uri: str,
    *,
    parameter_placeholder: str = "?",
    source_is_parquet: bool = False,
) -> list[tuple[str, str]]:
    if not source_is_parquet:
        return _fetch_delta_schema(conn, source_uri, parameter_placeholder=parameter_placeholder)
    cursor = conn.execute(
        f"SELECT * FROM read_parquet({parameter_placeholder}, union_by_name=true, hive_partitioning=true) LIMIT 0",
        [source_uri],
    )
    return _schema_from_cursor_description(cursor)


def _get_column_type_from_schema(schema: list[tuple[str, str]], column_name: str) -> str | None:
    """Get a column's type from a schema list, case-insensitive."""
    normalized_name = column_name.lower()
    for name, col_type in schema:
        if name.lower() == normalized_name:
            return col_type
    return None


def _fetch_schema(conn: _VerificationConnection, table_name: str) -> list[tuple[str, str]]:
    """Fetch schema from a DuckLake table."""
    cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT 0")
    return _schema_from_cursor_description(cursor)


def _schema_from_cursor_description(cursor: _VerificationCursor) -> list[tuple[str, str]]:
    description = cursor.description
    if not description:
        raise ValueError("Schema query did not return column metadata")

    schema: list[tuple[str, str]] = []
    for column in description:
        name = getattr(column, "name", None)
        type_code = getattr(column, "type_code", None)
        if name is None and isinstance(column, tuple):
            name = column[0] if len(column) > 0 else None
            type_code = column[1] if len(column) > 1 else None
        schema.append((str(name or ""), str(type_code or "")))
    return schema


def _diff_schema(source_schema: list[tuple[str, str]], ducklake_schema: list[tuple[str, str]]) -> list[str]:
    """Compare schemas and return list of mismatches."""
    mismatches: list[str] = []
    source_map = _schema_map(source_schema)
    ducklake_map = _schema_map(ducklake_schema)

    source_keys = set(source_map.keys())
    ducklake_keys = set(ducklake_map.keys())

    for key in sorted(source_keys - ducklake_keys):
        column_name, _ = source_map[key]
        mismatches.append(f"{column_name} missing from DuckLake")

    for key in sorted(ducklake_keys - source_keys):
        column_name, _ = ducklake_map[key]
        mismatches.append(f"{column_name} missing from Delta source")

    for key in sorted(source_keys & ducklake_keys):
        source_name, source_type = source_map[key]
        _, ducklake_type = ducklake_map[key]
        if source_type != ducklake_type:
            mismatches.append(f"{source_name} type mismatch (delta={source_type}, ducklake={ducklake_type})")

    return mismatches


def _schema_map(schema: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Create a normalized map of column names to (original_name, type)."""
    mapping: dict[str, tuple[str, str]] = {}
    for name, column_type in schema:
        normalized_name = (name or "").strip().lower()
        mapping[normalized_name] = (name, (column_type or "").strip())
    return mapping


def _build_partition_bucket_expression(column_name: str, column_type: str | None) -> str:
    """Build a SQL expression for partition bucketing."""
    column_expr = _quote_identifier(column_name)
    if _is_datetime_column_type(column_type):
        return f"date_trunc('day', {column_expr})"
    return column_expr


def _is_datetime_column_type(column_type: str | None) -> bool:
    """Check if a DuckDB column type is a datetime type."""
    if not column_type:
        return False
    normalized = column_type.strip().lower()
    return "date" in normalized or "time" in normalized


def _quote_identifier(identifier: str) -> str:
    """Quote a SQL identifier."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


@workflow.defn(name="ducklake-copy.data-imports")
class DuckLakeCopyDataImportsWorkflow(PostHogWorkflow):
    """Temporal workflow that copies data imports into the DuckLake bucket."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DataImportsDuckLakeCopyInputs:
        loaded = json.loads(inputs[0])
        schema_ids = [uuid.UUID(sid) if isinstance(sid, str) else sid for sid in loaded.get("schema_ids", [])]
        return DataImportsDuckLakeCopyInputs(
            team_id=loaded["team_id"],
            job_id=loaded["job_id"],
            schema_ids=schema_ids,
            prepared_queryable_folders=loaded.get("prepared_queryable_folders", {}),
        )

    @workflow.run
    async def run(self, inputs: DataImportsDuckLakeCopyInputs) -> None:
        logger = LOGGER.bind(**inputs.properties_to_log)
        logger.info("Starting DuckLakeCopyDataImportsWorkflow")

        if not inputs.schema_ids:
            logger.info("No schema_ids to copy - exiting early")
            return

        should_copy = await workflow.execute_activity(
            ducklake_copy_data_imports_gate_activity,
            DuckLakeCopyWorkflowGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if not should_copy:
            logger.info("DuckLake copy workflow disabled by feature flag")
            return

        model_list: list[DuckLakeCopyDataImportsMetadata] = await workflow.execute_activity(
            prepare_data_imports_ducklake_metadata_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not model_list:
            logger.info("No DuckLake copy metadata resolved - nothing to do")
            return

        pending_staging_cleanup: list[str] = []
        failed = False
        try:
            for model in model_list:
                activity_inputs = DuckLakeCopyDataImportsActivityInputs(
                    team_id=inputs.team_id, job_id=inputs.job_id, model=model
                )
                copy_applied = await workflow.execute_activity(
                    copy_data_imports_to_ducklake_activity,
                    activity_inputs,
                    # TODO: Adjust timeouts based on table size?
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                if copy_applied is False:
                    logger.info("Skipped a stale prepared Parquet generation", model_label=model.model_label)
                    continue

                if model.staging_uri:
                    pending_staging_cleanup.append(model.staging_uri)

                verification_results = await workflow.execute_activity(
                    verify_data_imports_ducklake_copy_activity,
                    activity_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                if verification_results:
                    for result in verification_results:
                        status = "passed" if result.passed else "failed"
                        get_ducklake_copy_data_imports_verification_metric(result.name, status).add(1)

                failed_checks = [result for result in verification_results if not result.passed]
                if failed_checks:
                    failure_payload = [dataclasses.asdict(result) for result in failed_checks]
                    logger.error(
                        "DuckLake verification failed",
                        model_label=model.model_label,
                        failures=failure_payload,
                    )
                    raise ApplicationError(
                        f"DuckLake copy verification failed: {failure_payload}",
                        non_retryable=True,
                    )

                if model.staging_uri:
                    await workflow.execute_activity(
                        cleanup_data_imports_staging_activity,
                        DuckLakeDataImportsStagingCleanupInputs(
                            team_id=inputs.team_id,
                            staging_uri=model.staging_uri,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    pending_staging_cleanup.remove(model.staging_uri)
        except Exception:
            failed = True
            get_ducklake_copy_data_imports_finished_metric(status="failed").add(1)
            raise
        finally:
            for staging_uri in pending_staging_cleanup:
                try:
                    await workflow.execute_activity(
                        cleanup_data_imports_staging_activity,
                        DuckLakeDataImportsStagingCleanupInputs(
                            team_id=inputs.team_id,
                            staging_uri=staging_uri,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except Exception:
                    workflow.logger.warning(
                        "Failed to clean up staging files",
                        staging_uri=staging_uri,
                    )

        if not failed:
            get_ducklake_copy_data_imports_finished_metric(status="completed").add(1)
