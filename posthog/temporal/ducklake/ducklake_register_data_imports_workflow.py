import re
import json
import uuid
import typing
import datetime as dt
import contextlib
import dataclasses
from collections.abc import Iterator

from django.conf import settings
from django.db import close_old_connections

import psycopg
from psycopg import sql as psql
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.ducklake.client import make_duckgres_conninfo
from posthog.ducklake.common import (
    _get_org_id_for_team,
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    get_config,
    get_duckgres_server_by_team_org,
    get_duckgres_server_for_organization,
    is_dev_mode,
)
from posthog.ducklake.storage import connect_to_duckgres, setup_duckgres_session
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ducklake.metrics import get_ducklake_register_data_imports_finished_metric

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

LOGGER = get_logger(__name__)
DUCKLAKE_DATA_IMPORTS_REGISTRATION_WORKFLOW_FLAG = "ducklake-data-imports-registration-workflow"
DATA_IMPORTS_GENERATIONS_PREFIX = "_imports"


@dataclasses.dataclass
class DuckLakeRegisterDataImportsGateInputs:
    team_id: int


@dataclasses.dataclass
class DuckLakeRegisterDataImportsInputs:
    team_id: int
    job_id: str
    schema_id: uuid.UUID
    prepared_queryable_folder: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": str(self.schema_id),
            "prepared_queryable_folder": self.prepared_queryable_folder,
        }


@dataclasses.dataclass
class DuckLakeRegisterDataImportsMetadata:
    source_schema_id: str
    prepared_queryable_folder: str
    prepared_source_uri: str
    landing_uri: str
    ducklake_schema_name: str
    ducklake_table_name: str


@dataclasses.dataclass
class DuckLakeRegisterDataImportsActivityInputs:
    team_id: int
    job_id: str
    metadata: DuckLakeRegisterDataImportsMetadata


class _StalePreparedGenerationError(Exception):
    pass


@activity.defn
async def ducklake_register_data_imports_gate_activity(inputs: DuckLakeRegisterDataImportsGateInputs) -> bool:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports registration gate")
        return False

    try:
        return feature_enabled_or_false(
            DUCKLAKE_DATA_IMPORTS_REGISTRATION_WORKFLOW_FLAG,
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        await logger.awarning("Failed to evaluate DuckLake data imports registration feature flag", error=str(error))
        capture_exception(error)
        return False


@activity.defn
async def prepare_ducklake_data_imports_registration_activity(
    inputs: DuckLakeRegisterDataImportsInputs,
) -> DuckLakeRegisterDataImportsMetadata | None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(schema_id=str(inputs.schema_id), job_id=inputs.job_id)

    if not _is_valid_queryable_folder(inputs.prepared_queryable_folder):
        raise ApplicationError(
            f"Invalid prepared queryable folder '{inputs.prepared_queryable_folder}'",
            non_retryable=True,
        )

    schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("table", "source").get)(
        id=inputs.schema_id,
        team_id=inputs.team_id,
    )
    if schema.table is None or schema.table.queryable_folder != inputs.prepared_queryable_folder:
        await logger.ainfo(
            "Skipping stale prepared Parquet generation before registration",
            prepared_queryable_folder=inputs.prepared_queryable_folder,
        )
        return None

    prepared_source_uri = f"{settings.BUCKET_URL}/{schema.folder_path()}/{inputs.prepared_queryable_folder}"
    ducklake_schema_name = await database_sync_to_async(duckgres_data_imports_schema)(inputs.team_id)
    ducklake_table_name = duckgres_data_imports_table_name(schema)
    landing_uri = await database_sync_to_async(_resolve_data_imports_landing_uri)(
        team_id=inputs.team_id,
        ducklake_schema_name=ducklake_schema_name,
        ducklake_table_name=ducklake_table_name,
        source_schema_id=str(inputs.schema_id),
        job_id=inputs.job_id,
    )
    return DuckLakeRegisterDataImportsMetadata(
        source_schema_id=str(schema.id),
        prepared_queryable_folder=inputs.prepared_queryable_folder,
        prepared_source_uri=prepared_source_uri,
        landing_uri=landing_uri,
        ducklake_schema_name=ducklake_schema_name,
        ducklake_table_name=ducklake_table_name,
    )


@activity.defn
def copy_and_register_ducklake_data_imports_activity(inputs: DuckLakeRegisterDataImportsActivityInputs) -> bool:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(
        schema_id=inputs.metadata.source_schema_id,
        job_id=inputs.job_id,
    )
    if not settings.TEST:
        close_old_connections()

    heartbeater = HeartbeaterSync(
        details=("ducklake_register_data_imports", inputs.metadata.source_schema_id),
        logger=logger,
    )
    with heartbeater:
        landing_paths = _copy_prepared_parquet_files(
            inputs.metadata.prepared_source_uri,
            inputs.metadata.landing_uri,
        )
        if not _prepared_generation_is_current(inputs):
            logger.info("Skipping stale prepared Parquet generation after object copy")
            return False

        try:
            with _connect_to_duckgres_for_team(inputs.team_id) as conn:
                _register_prepared_parquet_files(inputs, conn, landing_paths)
        except _StalePreparedGenerationError:
            logger.info("Skipping stale prepared Parquet generation before catalog swap")
            return False

    logger.info(
        "Copied, verified, and registered prepared Parquet files in DuckLake",
        ducklake_table=f"{inputs.metadata.ducklake_schema_name}.{inputs.metadata.ducklake_table_name}",
        file_count=len(landing_paths),
        landing_uri=inputs.metadata.landing_uri,
    )
    return True


def _is_valid_queryable_folder(queryable_folder: str) -> bool:
    return bool(queryable_folder) and "/" not in queryable_folder and queryable_folder not in {".", ".."}


def _resolve_data_imports_landing_uri(
    *,
    team_id: int,
    ducklake_schema_name: str,
    ducklake_table_name: str,
    source_schema_id: str,
    job_id: str,
) -> str:
    if is_dev_mode():
        bucket = get_config().get("DUCKLAKE_BUCKET")
    else:
        server = get_duckgres_server_by_team_org(team_id)
        bucket = server.bucket if server is not None else None
    if not bucket:
        raise ApplicationError(f"No S3 bucket configured for team {team_id}", non_retryable=True)

    safe_job_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job_id))
    return (
        f"s3://{bucket}/{ducklake_schema_name}/{ducklake_table_name}/"
        f"{DATA_IMPORTS_GENERATIONS_PREFIX}/{source_schema_id}/{safe_job_id}"
    )


def _copy_prepared_parquet_files(source_uri: str, landing_uri: str) -> list[str]:
    source_prefix = source_uri.removeprefix("s3://").rstrip("/")
    landing_prefix = landing_uri.removeprefix("s3://").rstrip("/")
    s3 = get_s3_client()
    found = s3.find(source_prefix)
    source_paths = list(found.keys()) if isinstance(found, dict) else list(found)
    parquet_paths = sorted(str(path) for path in source_paths if str(path).lower().endswith(".parquet"))
    if not parquet_paths:
        raise ApplicationError(f"No prepared Parquet files found under {source_uri}", non_retryable=True)

    landing_paths: list[str] = []
    for source_path_value in parquet_paths:
        source_path = source_path_value.removeprefix("s3://")
        relative_path = source_path.removeprefix(f"{source_prefix}/")
        if relative_path == source_path or relative_path.startswith("../"):
            raise ApplicationError(f"Prepared file escaped source prefix: {source_path}", non_retryable=True)
        landing_path = f"{landing_prefix}/{relative_path}"
        s3.copy(source_path, landing_path)
        landing_paths.append(f"s3://{landing_path}")

    return landing_paths


def _prepared_generation_is_current(inputs: DuckLakeRegisterDataImportsActivityInputs) -> bool:
    try:
        schema = ExternalDataSchema.objects.select_related("table").get(
            id=inputs.metadata.source_schema_id,
            team_id=inputs.team_id,
        )
    except ExternalDataSchema.DoesNotExist:
        return False
    return schema.table is not None and schema.table.queryable_folder == inputs.metadata.prepared_queryable_folder


@contextlib.contextmanager
def _connect_to_duckgres_for_team(team_id: int) -> Iterator[psycopg.Connection]:
    if is_dev_mode():
        with psycopg.connect(make_duckgres_conninfo(team_id), autocommit=True) as conn:
            yield conn
        return

    organization_id = _get_org_id_for_team(team_id)
    server = get_duckgres_server_for_organization(organization_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {team_id}", non_retryable=True)
    with connect_to_duckgres(server) as conn:
        yield conn


def _register_prepared_parquet_files(
    inputs: DuckLakeRegisterDataImportsActivityInputs,
    conn: psycopg.Connection,
    landing_paths: list[str],
) -> None:
    schema_name = inputs.metadata.ducklake_schema_name
    table_name = inputs.metadata.ducklake_table_name
    shadow_name = _data_imports_shadow_table_name(inputs)
    parquet_paths = psql.SQL("[{}]").format(psql.SQL(", ").join(psql.Literal(path) for path in landing_paths))
    partition_columns = _hive_partition_columns(inputs.metadata.landing_uri, landing_paths)

    setup_duckgres_session(conn, extensions=("ducklake", "httpfs"))
    with conn.transaction():
        conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(schema_name)))
        conn.execute(
            psql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                psql.Identifier(schema_name),
                psql.Identifier(shadow_name),
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
        if partition_columns:
            conn.execute(
                psql.SQL("ALTER TABLE {}.{} SET PARTITIONED BY ({})").format(
                    psql.Identifier(schema_name),
                    psql.Identifier(shadow_name),
                    psql.SQL(", ").join(psql.Identifier(column) for column in partition_columns),
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

        source_row = conn.execute(
            psql.SQL("SELECT count(*) FROM read_parquet({}, union_by_name=true, hive_partitioning=true)").format(
                parquet_paths
            )
        ).fetchone()
        registered_row = conn.execute(
            psql.SQL("SELECT count(*) FROM {}.{}").format(
                psql.Identifier(schema_name),
                psql.Identifier(shadow_name),
            )
        ).fetchone()
        source_count = int(source_row[0]) if source_row else 0
        registered_count = int(registered_row[0]) if registered_row else 0
        if source_count != registered_count:
            raise ApplicationError(
                "DuckLake prepared-file registration row count mismatch: "
                f"source={source_count}, registered={registered_count}",
                non_retryable=True,
            )

        if not _prepared_generation_is_current(inputs):
            raise _StalePreparedGenerationError

        conn.execute(
            psql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                psql.Identifier(schema_name),
                psql.Identifier(table_name),
            )
        )
        conn.execute(
            psql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                psql.Identifier(schema_name),
                psql.Identifier(shadow_name),
                psql.Identifier(table_name),
            )
        )


def _data_imports_shadow_table_name(inputs: DuckLakeRegisterDataImportsActivityInputs) -> str:
    schema_fragment = re.sub(r"[^A-Za-z0-9]", "", inputs.metadata.source_schema_id)[:8]
    job_fragment = re.sub(r"[^A-Za-z0-9]", "", inputs.job_id)[:8]
    return f"__ph_register_{schema_fragment}_{job_fragment}"


def _hive_partition_columns(landing_uri: str, landing_paths: list[str]) -> list[str]:
    landing_prefix = landing_uri.rstrip("/") + "/"
    columns: list[str] = []
    for landing_path in landing_paths:
        relative_path = landing_path.removeprefix(landing_prefix)
        for segment in relative_path.split("/")[:-1]:
            column, separator, _ = segment.partition("=")
            if separator and column and column not in columns:
                columns.append(column)
    return columns


@workflow.defn(name="ducklake-register.data-imports")
class DuckLakeRegisterDataImportsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> DuckLakeRegisterDataImportsInputs:
        loaded = json.loads(inputs[0])
        schema_id = loaded["schema_id"]
        return DuckLakeRegisterDataImportsInputs(
            team_id=loaded["team_id"],
            job_id=loaded["job_id"],
            schema_id=uuid.UUID(schema_id) if isinstance(schema_id, str) else schema_id,
            prepared_queryable_folder=loaded["prepared_queryable_folder"],
        )

    @workflow.run
    async def run(self, inputs: DuckLakeRegisterDataImportsInputs) -> None:
        logger = LOGGER.bind(**inputs.properties_to_log)
        logger.info("Starting DuckLakeRegisterDataImportsWorkflow")

        should_register = await workflow.execute_activity(
            ducklake_register_data_imports_gate_activity,
            DuckLakeRegisterDataImportsGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if not should_register:
            logger.info("DuckLake data imports registration workflow disabled by feature flag")
            return

        metadata = await workflow.execute_activity(
            prepare_ducklake_data_imports_registration_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if metadata is None:
            logger.info("Prepared Parquet generation is stale; nothing to register")
            return

        activity_inputs = DuckLakeRegisterDataImportsActivityInputs(
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            metadata=metadata,
        )
        try:
            copy_applied = await workflow.execute_activity(
                copy_and_register_ducklake_data_imports_activity,
                activity_inputs,
                start_to_close_timeout=dt.timedelta(minutes=30),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if not copy_applied:
                logger.info("Prepared Parquet generation became stale; registration skipped")
                get_ducklake_register_data_imports_finished_metric(status="stale").add(1)
                return

        except Exception:
            get_ducklake_register_data_imports_finished_metric(status="failed").add(1)
            raise

        get_ducklake_register_data_imports_finished_metric(status="completed").add(1)
