import re
import uuid
import typing
import dataclasses
from urllib.parse import urlparse

from django.conf import settings

import duckdb
import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.ducklake.common import (
    attach_catalog,
    configure_connection,
    escape as ducklake_escape,
    get_config,
)
from posthog.ducklake.verification import DuckLakeCopyVerificationQuery, get_data_imports_verification_queries
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.s3 import ensure_bucket_exists

LOGGER = get_logger(__name__)
DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX = "data_imports"

_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")


@dataclasses.dataclass
class DuckLakeCopyWorkflowGateInputs:
    """Inputs for the DuckLake copy workflow gate activity."""

    team_id: int


@dataclasses.dataclass
class DuckLakeCopyDataImportsModelInput:
    """Metadata describing a data imports schema to copy into DuckLake."""

    schema_id: uuid.UUID
    schema_name: str
    source_type: str
    normalized_name: str
    table_uri: str
    job_id: str
    team_id: int


@dataclasses.dataclass
class DataImportsDuckLakeCopyInputs:
    """Workflow inputs passed to DuckLakeCopyDataImportsWorkflow."""

    team_id: int
    job_id: str
    models: list[DuckLakeCopyDataImportsModelInput]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_ids": [str(model.schema_id) for model in self.models],
            "schema_names": [model.schema_name for model in self.models],
            "source_types": [model.source_type for model in self.models],
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
    source_partition_column_type: str | None = None
    source_key_columns: list[str] = dataclasses.field(default_factory=list)
    source_non_nullable_columns: list[str] = dataclasses.field(default_factory=list)

    # Verification
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DuckLakeCopyDataImportsActivityInputs:
    """Inputs for a single model copy activity."""

    team_id: int
    job_id: str
    model: DuckLakeCopyDataImportsMetadata


@activity.defn
async def ducklake_copy_data_imports_gate_activity(inputs: DuckLakeCopyWorkflowGateInputs) -> bool:
    """Evaluate whether the DuckLake data imports copy workflow should run for a team."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports gate")
        return False

    try:
        return posthoganalytics.feature_enabled(
            "ducklake-copy-data-imports",
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

    if not inputs.models:
        await logger.ainfo("DuckLake copy requested but no models were provided - skipping")
        return []

    model_list: list[DuckLakeCopyDataImportsMetadata] = []

    for model_input in inputs.models:
        schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("team", "table", "source").get)(
            id=model_input.schema_id, team_id=inputs.team_id
        )

        normalized_name = schema.normalized_name
        source_type = schema.source.source_type
        source_table_uri = f"{settings.BUCKET_URL}/{schema.folder_path()}/{normalized_name}"

        table_columns = schema.table.columns if schema.table else {}
        partition_column, partition_column_type = _detect_data_imports_partition_column(
            schema, table_columns, source_table_uri
        )
        key_columns = _detect_data_imports_key_columns(schema, table_columns)
        non_nullable_columns = _detect_data_imports_non_nullable_columns(table_columns)

        model_list.append(
            DuckLakeCopyDataImportsMetadata(
                model_label=f"{source_type}_{normalized_name}",
                source_schema_id=str(schema.id),
                source_schema_name=schema.name,
                source_normalized_name=normalized_name,
                source_table_uri=source_table_uri,
                ducklake_schema_name=_sanitize_ducklake_identifier(
                    f"{DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX}_team_{inputs.team_id}",
                    default_prefix=DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX,
                ),
                ducklake_table_name=_sanitize_ducklake_identifier(
                    f"{source_type}_{normalized_name}_{schema.id.hex[:8]}", default_prefix="data_imports"
                ),
                verification_queries=list(get_data_imports_verification_queries(normalized_name)),
                source_partition_column=partition_column,
                source_partition_column_type=partition_column_type,
                source_key_columns=key_columns,
                source_non_nullable_columns=non_nullable_columns,
            )
        )

    return model_list


@activity.defn
def copy_data_imports_to_ducklake_activity(inputs: DuckLakeCopyDataImportsActivityInputs) -> None:
    """Copy a single data imports schema's Delta snapshot into DuckLake."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    heartbeater = HeartbeaterSync(details=("ducklake_copy", inputs.model.model_label), logger=logger)
    with heartbeater:
        config = get_config()
        conn = duckdb.connect()
        alias = "ducklake"
        try:
            _configure_source_storage(conn, logger)
            configure_connection(conn, config, install_extension=True)
            _ensure_ducklake_bucket_exists(config)
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
        finally:
            conn.close()


def _detect_data_imports_partition_column(
    schema: ExternalDataSchema, columns: dict[str, typing.Any], table_uri: str
) -> tuple[str | None, str | None]:
    """Detect partition column for data imports tables.

    Checks:
    1. Schema partitioning config (partitioning_keys)
    2. _ph_partition_key column (standard data imports partition key)
    """
    if schema.partitioning_enabled and schema.partitioning_keys:
        partition_key = schema.partitioning_keys[0]
        if partition_key in columns:
            metadata = columns.get(partition_key)
            partition_column_type = _extract_column_type(metadata)
            return partition_key, partition_column_type or None

    if PARTITION_KEY in columns:
        metadata = columns.get(PARTITION_KEY)
        column_type = _extract_column_type(metadata)
        return PARTITION_KEY, column_type or None

    LOGGER.warning(
        "Unable to detect partition column for data imports - skipping partition verification.",
        schema_id=str(schema.id),
        table_uri=table_uri,
    )
    return None, None


def _detect_data_imports_key_columns(schema: ExternalDataSchema, columns: dict[str, typing.Any]) -> list[str]:
    """Detect key columns for data imports with preference order."""
    detected: list[str] = []

    if schema.incremental_field and schema.incremental_field in columns:
        detected.append(schema.incremental_field)

    if schema.partitioning_enabled and schema.partitioning_keys:
        for partition_key in schema.partitioning_keys:
            if partition_key in columns and partition_key not in detected:
                detected.append(partition_key)

    for name in columns.keys():
        lowered = name.lower()
        if lowered in ("id", "_id", "distinct_id", "person_id") and name not in detected:
            detected.append(name)
        elif lowered.endswith("_id") and name not in detected:
            detected.append(name)

    return detected


def _extract_column_type(metadata: typing.Any) -> str:
    """Extract ClickHouse column type from metadata."""
    if isinstance(metadata, dict):
        value = metadata.get("clickhouse") or metadata.get("type")
        if isinstance(value, str):
            return value
    if isinstance(metadata, str):
        return metadata
    return ""


def _detect_data_imports_non_nullable_columns(columns: dict[str, typing.Any]) -> list[str]:
    """Detect non-nullable columns from ClickHouse column types."""
    result: list[str] = []
    for name, metadata in columns.items():
        column_type = _extract_column_type(metadata)
        if column_type and not column_type.lower().startswith("nullable("):
            result.append(name)
    return result


def _sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    """Normalize identifiers so they are safe for DuckDB (lowercase alnum + underscores)."""
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:63]


def _configure_source_storage(conn: duckdb.DuckDBPyConnection, logger) -> None:
    """Configure DuckDB to read from source Delta tables in object storage."""
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("INSTALL delta")
    conn.execute("LOAD delta")

    access_key = settings.AIRBYTE_BUCKET_KEY
    secret_key = settings.AIRBYTE_BUCKET_SECRET
    region = getattr(settings, "AIRBYTE_BUCKET_REGION", "")

    endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") or ""
    normalized_endpoint = ""
    use_ssl = True
    if endpoint:
        normalized_endpoint, use_ssl = _normalize_object_storage_endpoint(endpoint)

    secret_parts = ["TYPE S3"]
    if access_key:
        secret_parts.append(f"KEY_ID '{ducklake_escape(access_key)}'")
    if secret_key:
        secret_parts.append(f"SECRET '{ducklake_escape(secret_key)}'")
    if region:
        secret_parts.append(f"REGION '{ducklake_escape(region)}'")
    if normalized_endpoint:
        secret_parts.append(f"ENDPOINT '{ducklake_escape(normalized_endpoint)}'")
    secret_parts.append(f"USE_SSL {'true' if use_ssl else 'false'}")
    secret_parts.append("URL_STYLE 'path'")
    conn.execute(f"CREATE OR REPLACE SECRET ducklake_minio ({', '.join(secret_parts)})")


def _normalize_object_storage_endpoint(endpoint: str) -> tuple[str, bool]:
    """Parse object storage endpoint to extract host and SSL setting."""
    parsed = endpoint.strip()
    if not parsed:
        return "", True

    if "://" in parsed:
        url = urlparse(parsed)
        host = url.netloc or url.path
        use_ssl = url.scheme.lower() == "https"
    else:
        host = parsed
        use_ssl = False

    return host.rstrip("/"), use_ssl


def _ensure_ducklake_bucket_exists(config: dict[str, str]) -> None:
    """Ensure the DuckLake data bucket exists (local dev only)."""
    if not settings.USE_LOCAL_SETUP:
        return

    ensure_bucket_exists(
        f"s3://{config['DUCKLAKE_DATA_BUCKET'].rstrip('/')}",
        config["DUCKLAKE_S3_ACCESS_KEY"],
        config["DUCKLAKE_S3_SECRET_KEY"],
        settings.OBJECT_STORAGE_ENDPOINT,
    )


def _attach_ducklake_catalog(conn: duckdb.DuckDBPyConnection, config: dict[str, str], alias: str) -> None:
    """Attach the DuckLake catalog, swallowing the error if already attached."""
    try:
        attach_catalog(conn, config, alias=alias)
    except duckdb.CatalogException as exc:
        if alias not in str(exc):
            raise
