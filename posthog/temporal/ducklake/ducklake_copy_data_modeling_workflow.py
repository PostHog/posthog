import re
import json
import datetime as dt
import dataclasses

import duckdb
import deltalake
import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.ducklake.common import attach_catalog, get_config
from posthog.ducklake.storage import configure_connection, ensure_ducklake_bucket_exists, get_deltalake_storage_options
from posthog.ducklake.verification import (
    DuckLakeCopyVerificationParameter,
    DuckLakeCopyVerificationQuery,
    get_data_modeling_verification_queries,
)
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ducklake.metrics import (
    get_ducklake_copy_data_modeling_finished_metric,
    get_ducklake_copy_data_modeling_verification_metric,
)
from posthog.temporal.ducklake.types import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

from products.data_warehouse.backend.models import DataWarehouseSavedQuery

LOGGER = get_logger(__name__)
DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX = "data_modeling"


@dataclasses.dataclass
class DuckLakeCopyModelMetadata:
    model_label: str
    saved_query_id: str
    saved_query_name: str
    normalized_name: str
    source_table_uri: str
    schema_name: str
    table_name: str
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)
    partition_column: str | None = None


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


@dataclasses.dataclass
class DuckLakeCopyWorkflowGateInputs:
    team_id: int


@activity.defn
async def ducklake_copy_workflow_gate_activity(inputs: DuckLakeCopyWorkflowGateInputs) -> bool:
    """Evaluate whether the DuckLake copy workflow should run for a team."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake copy workflow gate")
        return False

    try:
        return posthoganalytics.feature_enabled(
            "ducklake-data-modeling-copy-workflow",
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
            "Failed to evaluate DuckLake copy workflow feature flag",
            error=str(error),
        )
        capture_exception(error)
        return False


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

    model_list: list[DuckLakeCopyModelMetadata] = []

    for model in inputs.models:
        # Django: only for semantic naming (not stored in Delta)
        saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.only("id", "name").get)(
            id=model.saved_query_id
        )

        normalized_name = saved_query.normalized_name or saved_query.name

        # Get partition column name from Delta metadata
        partition_column = _detect_partition_column_name(model.table_uri)

        model_list.append(
            DuckLakeCopyModelMetadata(
                model_label=model.model_label,
                saved_query_id=str(saved_query.id),
                saved_query_name=saved_query.name,
                normalized_name=normalized_name,
                source_table_uri=model.table_uri,
                schema_name=_sanitize_ducklake_identifier(
                    f"{DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX}_team_{inputs.team_id}",
                    default_prefix=DATA_MODELING_DUCKLAKE_WORKFLOW_PREFIX,
                ),
                table_name=_sanitize_ducklake_identifier(model.model_label or normalized_name, default_prefix="model"),
                verification_queries=list(get_data_modeling_verification_queries(model.model_label)),
                partition_column=partition_column,
            )
        )

    return model_list


@activity.defn
def copy_data_modeling_model_to_ducklake_activity(inputs: DuckLakeCopyActivityInputs) -> None:
    """Ingest a single model's Delta snapshot into DuckLake using native SQL."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    heartbeater = HeartbeaterSync(details=("ducklake_copy", inputs.model.model_label), logger=logger)
    with heartbeater:
        config = get_config()
        conn = duckdb.connect()
        alias = "ducklake"
        try:
            configure_connection(conn)
            ensure_ducklake_bucket_exists(config=config)
            _attach_ducklake_catalog(conn, config, alias=alias)

            qualified_schema = f"{alias}.{inputs.model.schema_name}"
            qualified_table = f"{qualified_schema}.{inputs.model.table_name}"

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


@activity.defn
def verify_ducklake_copy_activity(inputs: DuckLakeCopyActivityInputs) -> list[DuckLakeCopyVerificationResult]:
    """Run configured DuckDB verification queries to ensure the copy matches the source."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)

    if not inputs.model.verification_queries:
        logger.info("No DuckLake verification queries configured - skipping")
        return []

    heartbeater = HeartbeaterSync(details=("ducklake_verify", inputs.model.model_label), logger=logger)
    with heartbeater:
        config = get_config()
        conn = duckdb.connect()
        alias = "ducklake"
        results: list[DuckLakeCopyVerificationResult] = []

        try:
            configure_connection(conn)
            _attach_ducklake_catalog(conn, config, alias=alias)

            ducklake_table = f"{alias}.{inputs.model.schema_name}.{inputs.model.table_name}"
            format_values = {
                "ducklake_table": ducklake_table,
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

            schema_result = _run_schema_verification(conn, ducklake_table, inputs)
            if schema_result:
                results.append(schema_result)

            partition_result = _run_partition_verification(conn, ducklake_table, inputs)
            if partition_result:
                results.append(partition_result)
        finally:
            conn.close()

    failed = [result for result in results if not result.passed]
    if failed:
        logger.warning(
            "DuckLake verification checks failed",
            model_label=inputs.model.model_label,
            failures=[dataclasses.asdict(result) for result in failed],
        )

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
        logger = LOGGER.bind(**inputs.properties_to_log)
        logger.info("Starting DuckLakeCopyDataModelingWorkflow")

        if not inputs.models:
            logger.info("No models to copy - exiting early")
            return

        should_copy = await workflow.execute_activity(
            ducklake_copy_workflow_gate_activity,
            DuckLakeCopyWorkflowGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if not should_copy:
            logger.info("DuckLake copy workflow disabled by feature flag")
            return

        model_list: list[DuckLakeCopyModelMetadata] = await workflow.execute_activity(
            prepare_data_modeling_ducklake_metadata_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not model_list:
            logger.info("No DuckLake copy metadata resolved - nothing to do")
            return

        try:
            for model in model_list:
                activity_inputs = DuckLakeCopyActivityInputs(team_id=inputs.team_id, job_id=inputs.job_id, model=model)
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
        except Exception:
            get_ducklake_copy_data_modeling_finished_metric(status="failed").add(1)
            raise

        get_ducklake_copy_data_modeling_finished_metric(status="completed").add(1)


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


def _detect_partition_column_name(table_uri: str) -> str | None:
    """Detect partition column name from Delta metadata."""
    if not table_uri:
        return None

    partition_columns = _fetch_delta_partition_columns(table_uri)

    # Return the first partition column
    return partition_columns[0] if partition_columns else None


def _fetch_delta_partition_columns(table_uri: str) -> list[str]:
    options = get_deltalake_storage_options()
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


def _get_column_type_from_schema(schema: list[tuple[str, str]], column_name: str) -> str | None:
    """Get a column's type from a schema list, case-insensitive."""
    normalized_name = column_name.lower()
    for name, col_type in schema:
        if name.lower() == normalized_name:
            return col_type
    return None


def _is_datetime_column_type(column_type: str | None) -> bool:
    if not column_type:
        return False
    normalized = column_type.strip().lower()
    return "date" in normalized or "time" in normalized


def _run_schema_verification(
    conn: duckdb.DuckDBPyConnection, ducklake_table: str, inputs: DuckLakeCopyActivityInputs
) -> DuckLakeCopyVerificationResult | None:
    try:
        source_schema = _fetch_delta_schema(conn, inputs.model.source_table_uri)
        ducklake_schema = _fetch_schema(conn, ducklake_table)
    except Exception as exc:
        return DuckLakeCopyVerificationResult(
            name="model.schema_hash",
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

    return DuckLakeCopyVerificationResult(
        name="model.schema_hash",
        passed=passed,
        description="Compare schema hash between Delta source and DuckLake table.",
        expected_value=0.0,
        observed_value=0.0 if passed else 1.0,
        tolerance=0.0,
        error=error,
    )


def _run_partition_verification(
    conn: duckdb.DuckDBPyConnection,
    ducklake_table: str,
    inputs: DuckLakeCopyActivityInputs,
) -> DuckLakeCopyVerificationResult | None:
    partition_column = inputs.model.partition_column
    if not partition_column:
        return None

    # Fetch partition column type from Delta schema at verification time
    source_schema = _fetch_delta_schema(conn, inputs.model.source_table_uri)
    partition_column_type = _get_column_type_from_schema(source_schema, partition_column)
    if partition_column_type is None:
        return DuckLakeCopyVerificationResult(
            name="model.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=f"Partition column '{partition_column}' not found in Delta schema",
        )

    bucket_expr = _build_partition_bucket_expression(partition_column, partition_column_type)
    sql = f"""
        WITH source AS (
            SELECT {bucket_expr} AS bucket, count(*) AS cnt
            FROM delta_scan(?)
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
        mismatches = conn.execute(sql, [inputs.model.source_table_uri]).fetchall()
    except Exception as exc:
        return DuckLakeCopyVerificationResult(
            name="model.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=str(exc),
        )

    if mismatches:
        return DuckLakeCopyVerificationResult(
            name="model.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            expected_value=0.0,
            observed_value=float(len(mismatches)),
            tolerance=0.0,
            error=f"Partition mismatches detected: {mismatches[:5]}",
        )

    return DuckLakeCopyVerificationResult(
        name="model.partition_counts",
        passed=True,
        description="Ensure partition counts match between source and DuckLake.",
        expected_value=0.0,
        observed_value=0.0,
        tolerance=0.0,
    )


def _build_partition_bucket_expression(column_name: str, column_type: str | None) -> str:
    column_expr = _quote_identifier(column_name)
    # people should not use datetime types for partition columns
    # but AI lord made me check it
    if _is_datetime_column_type(column_type):
        return f"date_trunc('day', {column_expr})"
    return column_expr


def _diff_schema(source_schema: list[tuple[str, str]], ducklake_schema: list[tuple[str, str]]) -> list[str]:
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
    mapping: dict[str, tuple[str, str]] = {}
    for name, column_type in schema:
        normalized_name = (name or "").strip().lower()
        mapping[normalized_name] = (name, (column_type or "").strip())
    return mapping


def _fetch_delta_schema(conn: duckdb.DuckDBPyConnection, source_uri: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "DESCRIBE SELECT * FROM delta_scan(?) LIMIT 0",
        [source_uri],
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _fetch_schema(conn: duckdb.DuckDBPyConnection, table_name: str) -> list[tuple[str, str]]:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return [(row[1], row[2]) for row in rows]


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


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
        DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI: model.source_table_uri,
        DuckLakeCopyVerificationParameter.SCHEMA_NAME: model.schema_name,
        DuckLakeCopyVerificationParameter.TABLE_NAME: model.table_name,
    }

    if parameter not in mapping:
        raise ValueError(f"Unsupported DuckLake verification parameter '{parameter}'")

    return mapping[parameter]
