import re
import json
import datetime as dt
import dataclasses
from urllib.parse import urlparse

from django.conf import settings

import duckdb
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.ducklake.common import (
    attach_catalog,
    configure_connection,
    escape as ducklake_escape,
    get_config,
    normalize_endpoint,
)
from posthog.ducklake.verification import (
    DuckLakeCopyVerificationParameter,
    DuckLakeCopyVerificationQuery,
    get_data_modeling_verification_queries,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_modeling.metrics import (
    get_ducklake_copy_data_modeling_finished_metric,
    get_ducklake_copy_data_modeling_verification_metric,
)
from posthog.temporal.utils import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.s3 import ensure_bucket_exists

LOGGER = get_logger(__name__)
DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX = "data_modeling"


@dataclasses.dataclass
class DuckLakeCopyModelMetadata:
    model_label: str
    saved_query_id: str
    saved_query_name: str
    normalized_name: str
    source_glob_uri: str
    source_table_uri: str
    schema_name: str
    table_name: str
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DuckLakeCopyActivityInputs:
    team_id: int
    job_id: str
    model: DuckLakeCopyModelMetadata


@dataclasses.dataclass
class DuckLakeCopyVerificationResult:
    name: str
    passed: bool
    observed_value: float | None = None
    expected_value: float | None = None
    tolerance: float | None = None
    description: str | None = None
    sql: str | None = None
    error: str | None = None


@activity.defn
async def prepare_data_modeling_ducklake_metadata_activity(
    inputs: DataModelingDuckLakeCopyInputs,
) -> list[DuckLakeCopyModelMetadata]:
    """Resolve saved queries referenced in the workflow inputs into copy-ready metadata."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    if not inputs.models:
        await logger.ainfo("DuckLake copy requested but no models were provided - skipping")
        return []

    metadata: list[DuckLakeCopyModelMetadata] = []

    for model in inputs.models:
        saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.select_related("team").get)(
            id=model.saved_query_id
        )

        normalized_name = saved_query.normalized_name or saved_query.name
        metadata.append(
            DuckLakeCopyModelMetadata(
                model_label=model.model_label,
                saved_query_id=str(saved_query.id),
                saved_query_name=saved_query.name,
                normalized_name=normalized_name,
                source_glob_uri=_build_ducklake_source_glob(model.file_uris),
                source_table_uri=model.table_uri,
                schema_name=_sanitize_ducklake_identifier(
                    f"{DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX}_team_{inputs.team_id}",
                    default_prefix=DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX,
                ),
                table_name=_sanitize_ducklake_identifier(model.model_label or normalized_name, default_prefix="model"),
                verification_queries=list(get_data_modeling_verification_queries(model.model_label)),
            )
        )

    return metadata


@activity.defn
def copy_data_modeling_model_to_ducklake_activity(inputs: DuckLakeCopyActivityInputs) -> None:
    """Ingest a single model's Parquet snapshot into DuckLake using native SQL."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    config = get_config()
    conn = duckdb.connect()
    alias = "ducklake_dev"
    try:
        _configure_source_storage(conn, logger)
        configure_connection(conn, config, install_extension=True)
        _ensure_ducklake_bucket_exists(config)
        _attach_ducklake_catalog(conn, config, alias=alias)

        qualified_schema = f"{alias}.{inputs.model.schema_name}"
        qualified_table = f"{qualified_schema}.{inputs.model.table_name}"
        escaped_glob = ducklake_escape(inputs.model.source_glob_uri)

        logger.info(
            "Creating DuckLake table from Parquet snapshot",
            ducklake_table=qualified_table,
            source_glob=inputs.model.source_glob_uri,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {qualified_schema}")
        conn.execute(f"CREATE OR REPLACE TABLE {qualified_table} AS " f"SELECT * FROM read_parquet('{escaped_glob}')")
        logger.info("Successfully materialized DuckLake table", ducklake_table=qualified_table)
    finally:
        conn.close()


@activity.defn
def verify_ducklake_copy_activity(inputs: DuckLakeCopyActivityInputs) -> list[DuckLakeCopyVerificationResult]:
    """Run configured DuckDB verification queries to ensure the copy matches the source."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    if not inputs.model.verification_queries:
        logger.info("No DuckLake verification queries configured - skipping")
        return []

    config = get_config()
    conn = duckdb.connect()
    alias = "ducklake_dev"
    results: list[DuckLakeCopyVerificationResult] = []

    try:
        _configure_source_storage(conn, logger)
        configure_connection(conn, config, install_extension=True)
        _attach_ducklake_catalog(conn, config, alias=alias)

        format_values = {
            "ducklake_table": f"{alias}.{inputs.model.schema_name}.{inputs.model.table_name}",
            "ducklake_schema": f"{alias}.{inputs.model.schema_name}",
            "ducklake_alias": alias,
            "schema_name": inputs.model.schema_name,
            "table_name": inputs.model.table_name,
        }

        for query in inputs.model.verification_queries:
            rendered_sql = query.sql.format(**format_values)
            params = [_resolve_verification_parameter(param, inputs) for param in query.parameters]

            try:
                row = conn.execute(rendered_sql, params).fetchone()
            except Exception as exc:
                logger.warning(
                    "DuckLake verification query failed",
                    check=query.name,
                    error=str(exc),
                )
                results.append(
                    DuckLakeCopyVerificationResult(
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
                    DuckLakeCopyVerificationResult(
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

            raw_value = row[0]
            try:
                observed = float(raw_value)
            except (TypeError, ValueError):
                logger.warning(
                    "DuckLake verification query returned a non-numeric value",
                    check=query.name,
                    value=raw_value,
                )
                results.append(
                    DuckLakeCopyVerificationResult(
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
                DuckLakeCopyVerificationResult(
                    name=query.name,
                    passed=passed,
                    observed_value=observed,
                    expected_value=query.expected_value,
                    tolerance=tolerance,
                    description=query.description,
                    sql=rendered_sql,
                )
            )
    finally:
        conn.close()

    return results


@workflow.defn(name="ducklake-copy.data-modeling")
class DuckLakeCopyDataModelingWorkflow(PostHogWorkflow):
    """Temporal workflow that copies data modeling outputs into the DuckLake bucket."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DataModelingDuckLakeCopyInputs:
        loaded = json.loads(inputs[0])
        models = [DuckLakeCopyModelInput(**model) for model in loaded.get("models", [])]
        loaded["models"] = models
        return DataModelingDuckLakeCopyInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DataModelingDuckLakeCopyInputs) -> None:
        workflow.logger.info("Starting DuckLakeCopyDataModelingWorkflow", **inputs.properties_to_log)

        if not inputs.models:
            workflow.logger.info("No models to copy - exiting early", **inputs.properties_to_log)
            return

        metadata = await workflow.execute_activity(
            prepare_data_modeling_ducklake_metadata_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not metadata:
            workflow.logger.info("No DuckLake copy metadata resolved - nothing to do", **inputs.properties_to_log)
            return

        try:
            for target in metadata:
                activity_inputs = DuckLakeCopyActivityInputs(team_id=inputs.team_id, job_id=inputs.job_id, model=target)
                await workflow.execute_activity(
                    copy_data_modeling_model_to_ducklake_activity,
                    activity_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                    ),
                )

                verification_results = await workflow.execute_activity(
                    verify_ducklake_copy_activity,
                    activity_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        maximum_attempts=1,
                    ),
                )

                if verification_results:
                    for result in verification_results:
                        status = "passed" if result.passed else "failed"
                        get_ducklake_copy_data_modeling_verification_metric(result.name, status).add(1)

                failed_checks = [result for result in verification_results if not result.passed]
                if failed_checks:
                    workflow.logger.error(
                        "DuckLake verification failed",
                        model_label=target.model_label,
                        failures=[dataclasses.asdict(result) for result in failed_checks],
                    )
                    raise RuntimeError("DuckLake copy verification failed")
        except Exception:
            get_ducklake_copy_data_modeling_finished_metric(status="failed").add(1)
            raise

        get_ducklake_copy_data_modeling_finished_metric(status="completed").add(1)


def _configure_source_storage(conn: duckdb.DuckDBPyConnection, logger) -> None:
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
    parsed = endpoint.strip()
    if not parsed:
        return "", True

    if "://" in parsed:
        normalized, use_ssl = normalize_endpoint(parsed)
    else:
        use_ssl = parsed.lower().startswith("https")
        normalized = parsed.rstrip("/")

    return normalized, use_ssl


def _ensure_ducklake_bucket_exists(config: dict[str, str]) -> None:
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


_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")


def _sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    """Normalize identifiers so they are safe for DuckDB (lowercase alnum + underscores)."""
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:63]


def _build_ducklake_source_glob(file_uris: list[str]) -> str:
    """Derive a glob covering all Parquet files that make up the saved query snapshot."""
    if not file_uris:
        raise ValueError("DuckLake copy requires at least one Parquet file URI")

    base: str | None = None
    directory_segments: list[list[str]] = []
    for uri in file_uris:
        parsed = urlparse(uri)
        scheme = (parsed.scheme or "s3").lower()
        if scheme.startswith("s3"):
            scheme = "s3"
        if not parsed.netloc:
            raise ValueError(f"Unable to determine host/bucket for DuckLake URI '{uri}'")
        current_base = f"{scheme}://{parsed.netloc}"
        if base is None:
            base = current_base
        elif current_base != base:
            raise ValueError("DuckLake copy inputs must share the same base URI")

        stripped_path = parsed.path.lstrip("/")
        directory = stripped_path.rsplit("/", 1)[0] if "/" in stripped_path else ""
        directory_segments.append([segment for segment in directory.split("/") if segment])

    if base is None:
        raise ValueError("Invalid DuckLake file URIs - missing base path")

    common_segments = directory_segments[0][:]
    for segments in directory_segments[1:]:
        new_common: list[str] = []
        for left, right in zip(common_segments, segments):
            if left != right:
                break
            new_common.append(left)
        common_segments = new_common
        if not common_segments:
            break

    if not common_segments and any(directory_segments):
        raise ValueError("DuckLake copy inputs must share a common directory prefix")

    relative_prefix = "/".join(common_segments)
    normalized_base = base.rstrip("/")
    if relative_prefix:
        normalized_base = f"{normalized_base}/{relative_prefix}"

    return f"{normalized_base.rstrip('/')}/**/*.parquet"


def _resolve_verification_parameter(
    parameter: DuckLakeCopyVerificationParameter, inputs: DuckLakeCopyActivityInputs
) -> str | int:
    model = inputs.model
    mapping: dict[DuckLakeCopyVerificationParameter, str | int] = {
        DuckLakeCopyVerificationParameter.TEAM_ID: inputs.team_id,
        DuckLakeCopyVerificationParameter.JOB_ID: inputs.job_id,
        DuckLakeCopyVerificationParameter.MODEL_LABEL: model.model_label,
        DuckLakeCopyVerificationParameter.SAVED_QUERY_ID: model.saved_query_id,
        DuckLakeCopyVerificationParameter.SAVED_QUERY_NAME: model.saved_query_name,
        DuckLakeCopyVerificationParameter.NORMALIZED_NAME: model.normalized_name,
        DuckLakeCopyVerificationParameter.SOURCE_GLOB_URI: model.source_glob_uri,
        DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI: model.source_table_uri,
        DuckLakeCopyVerificationParameter.SCHEMA_NAME: model.schema_name,
        DuckLakeCopyVerificationParameter.TABLE_NAME: model.table_name,
    }

    if parameter not in mapping:
        raise ValueError(f"Unsupported DuckLake verification parameter '{parameter}'")

    return mapping[parameter]
