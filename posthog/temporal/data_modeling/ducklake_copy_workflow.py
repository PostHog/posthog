import json
import uuid
import datetime as dt
import dataclasses

from django.conf import settings

import duckdb
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.ducklake.common import (
    configure_connection,
    escape as ducklake_escape,
    get_config,
    normalize_endpoint,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_modeling.metrics import get_ducklake_copy_finished_metric
from posthog.temporal.utils import DuckLakeCopyModelInput, DuckLakeCopyWorkflowInputs

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.s3 import ensure_bucket_exists

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class DuckLakeCopyModelMetadata:
    model_label: str
    saved_query_id: str
    saved_query_name: str
    normalized_name: str
    table_uri: str
    destination_uri: str


@dataclasses.dataclass
class DuckLakeCopyActivityInputs:
    team_id: int
    job_id: str
    model: DuckLakeCopyModelMetadata


@activity.defn
async def prepare_ducklake_copy_metadata_activity(
    inputs: DuckLakeCopyWorkflowInputs,
) -> list[DuckLakeCopyModelMetadata]:
    """Resolve saved queries referenced in the workflow inputs into copy-ready metadata."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    if not inputs.models:
        await logger.ainfo("DuckLake copy requested but no models were provided - skipping")
        return []

    config = get_config()
    metadata: list[DuckLakeCopyModelMetadata] = []

    for model in inputs.models:
        saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.select_related("team").get)(
            id=model.saved_query_id
        )

        normalized_name = saved_query.normalized_name or saved_query.name
        destination_uri = _build_ducklake_destination_uri(
            bucket=config["DUCKLAKE_DATA_BUCKET"],
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            model_label=model.model_label,
            normalized_name=normalized_name,
        )
        metadata.append(
            DuckLakeCopyModelMetadata(
                model_label=model.model_label,
                saved_query_id=str(saved_query.id),
                saved_query_name=saved_query.name,
                normalized_name=normalized_name,
                table_uri=model.table_uri,
                destination_uri=destination_uri,
            )
        )

    await logger.ainfo("Prepared DuckLake copy metadata", models=len(metadata))
    return metadata


@activity.defn
def copy_model_to_ducklake_activity(inputs: DuckLakeCopyActivityInputs) -> None:
    """Copy a single model's Delta table into the DuckLake-managed Parquet bucket."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    config = get_config()
    conn = duckdb.connect()
    table_name = f"ducklake_src_{uuid.uuid4().hex}"
    try:
        _configure_source_storage(conn, logger)
        logger.ainfo("Loading Delta table into DuckDB", table_uri=inputs.model.table_uri)
        conn.execute(
            f"CREATE OR REPLACE TEMP TABLE {table_name} AS SELECT * FROM read_delta(?)",
            [inputs.model.table_uri],
        )

        configure_connection(conn, config, install_extension=True)
        _ensure_ducklake_bucket_exists(config)
        logger.ainfo("Copying model into DuckLake", destination=inputs.model.destination_uri)
        conn.execute(
            f"COPY (SELECT * FROM {table_name}) TO '{ducklake_escape(inputs.model.destination_uri)}' "
            " (FORMAT PARQUET, OVERWRITE_OR_REPLACE=TRUE)"
        )
        logger.ainfo("Successfully copied model into DuckLake")
    finally:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        except duckdb.Error:
            logger.awarning("Failed to drop temporary DuckDB table", temp_table=table_name)
        conn.close()


@workflow.defn(name="ducklake-copy")
class DuckLakeCopyWorkflow(PostHogWorkflow):
    """Temporal workflow that copies model outputs into the DuckLake bucket."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DuckLakeCopyWorkflowInputs:
        loaded = json.loads(inputs[0])
        models = [DuckLakeCopyModelInput(**model) for model in loaded.get("models", [])]
        loaded["models"] = models
        return DuckLakeCopyWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DuckLakeCopyWorkflowInputs) -> None:
        workflow.logger.info("Starting DuckLakeCopyWorkflow", **inputs.properties_to_log)

        if not inputs.models:
            workflow.logger.info("No models to copy - exiting early", **inputs.properties_to_log)
            return

        metadata = await workflow.execute_activity(
            prepare_ducklake_copy_metadata_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not metadata:
            workflow.logger.info("No DuckLake copy metadata resolved - nothing to do", **inputs.properties_to_log)
            return

        try:
            for target in metadata:
                await workflow.execute_activity(
                    copy_model_to_ducklake_activity,
                    DuckLakeCopyActivityInputs(team_id=inputs.team_id, job_id=inputs.job_id, model=target),
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                    ),
                )
        except Exception:
            get_ducklake_copy_finished_metric(status="failed").add(1)
            raise

        get_ducklake_copy_finished_metric(status="completed").add(1)


def _build_ducklake_destination_uri(
    *, bucket: str, team_id: int, job_id: str, model_label: str, normalized_name: str
) -> str:
    bucket = bucket.rstrip("/")
    return f"s3://{bucket}/data_modeling/team_{team_id}/job_{job_id}/model_{model_label}/{normalized_name}.parquet"


def _configure_source_storage(conn: duckdb.DuckDBPyConnection, logger) -> None:
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("INSTALL delta")
    conn.execute("LOAD delta")

    access_key = settings.AIRBYTE_BUCKET_KEY
    secret_key = settings.AIRBYTE_BUCKET_SECRET
    region = getattr(settings, "AIRBYTE_BUCKET_REGION", "")

    endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") or ""
    if endpoint:
        normalized_endpoint, use_ssl = _normalize_object_storage_endpoint(endpoint)
        conn.execute(f"SET s3_endpoint='{ducklake_escape(normalized_endpoint)}'")
        conn.execute(f"SET s3_use_ssl={'true' if use_ssl else 'false'}")
    if access_key:
        conn.execute(f"SET s3_access_key_id='{ducklake_escape(access_key)}'")
    if secret_key:
        conn.execute(f"SET s3_secret_access_key='{ducklake_escape(secret_key)}'")
    if region:
        conn.execute(f"SET s3_region='{ducklake_escape(region)}'")

    conn.execute("SET s3_url_style='path'")
    logger.adebug("Configured DuckDB connection for PostHog object storage access")


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
