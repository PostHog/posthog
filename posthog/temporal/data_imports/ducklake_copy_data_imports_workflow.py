import re
import uuid
import typing
import dataclasses

from django.conf import settings

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.ducklake.verification import DuckLakeCopyVerificationQuery, get_data_imports_verification_queries
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

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

    model_label: str
    schema_id: str
    schema_name: str
    normalized_name: str
    source_table_uri: str
    ducklake_schema_name: str
    ducklake_table_name: str
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)
    partition_column: str | None = None
    partition_column_type: str | None = None
    key_columns: list[str] = dataclasses.field(default_factory=list)
    non_nullable_columns: list[str] = dataclasses.field(default_factory=list)


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
                schema_id=str(schema.id),
                schema_name=schema.name,
                normalized_name=normalized_name,
                source_table_uri=source_table_uri,
                ducklake_schema_name=_sanitize_ducklake_identifier(
                    f"{DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX}_team_{inputs.team_id}",
                    default_prefix=DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX,
                ),
                ducklake_table_name=_sanitize_ducklake_identifier(
                    f"{source_type}_{normalized_name}_{schema.id.hex[:8]}", default_prefix="data_imports"
                ),
                verification_queries=list(get_data_imports_verification_queries(normalized_name)),
                partition_column=partition_column,
                partition_column_type=partition_column_type,
                key_columns=key_columns,
                non_nullable_columns=non_nullable_columns,
            )
        )

    return model_list


def _detect_data_imports_partition_column(
    schema: ExternalDataSchema, columns: dict[str, typing.Any], table_uri: str
) -> tuple[str | None, str | None]:
    """Detect partition column for data imports tables with fallback logic.

    Fallback order:
    1. Schema partitioning config (partitioning_keys)
    2. _ph_partition_key column (standard data imports partition key)
    3. First datetime column found
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

    for column_name, metadata in columns.items():
        column_type = _extract_column_type(metadata)
        if _is_datetime_column_type(column_type):
            return column_name, column_type

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


def _is_datetime_column_type(column_type: str | None) -> bool:
    """Check if column type is a date/time type."""
    if not column_type:
        return False
    normalized = column_type.strip().lower()
    return "date" in normalized or "time" in normalized


def _sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    """Normalize identifiers so they are safe for DuckDB (lowercase alnum + underscores)."""
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:63]
