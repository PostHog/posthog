import os
import time
import typing
import datetime as dt
import dataclasses
from uuid import UUID

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.hogql.transforms.trino.errors import TrinoLoweringError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade.api import (
    TRINO_INCREMENTAL_SCOPE,
    WritePlan,
    clear_incremental_state,
    resolve_write_plan,
    set_incremental_state,
    unbuilt_upstream_saved_query_ids,
)
from products.data_modeling.backend.facade.models import (
    TERMINAL_JOB_STATUSES,
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobRunMode,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)
from products.endpoints.backend.facade.temporal import prepare_executable_query
from products.managed_warehouse.backend.facade.api import (
    duckgres_data_modeling_schema,
    ducklake_data_modeling_schema,
    get_data_modeling_table_name,
    has_provisioned_warehouse,
    is_data_modeling_shadow_ready,
    is_dev_mode,
)
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeCompiledQuery,
    DuckLakeS3Secret,
    TrinoIncrementalWrite,
)
from products.managed_warehouse.backend.facade.feature_flags import DATA_MODELING_SHADOW_FLAG

from ..metrics import (
    UNKNOWN_RUN_MODE,
    get_managed_warehouse_trino_compile_failure_metric,
    get_managed_warehouse_trino_missing_object_metric,
    get_node_suspended_metric,
)
from .utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    bind_data_modeling_log_context,
    clear_node_suspension_for_engine,
    maybe_suspend_node_for_engine,
)

LOGGER = get_logger(__name__)

FEATURE_FLAG = DATA_MODELING_SHADOW_FLAG


@frozen
class ManagedWarehouseShadowEligibilityInputs:
    team_id: int
    dag_id: str
    node_id: str


@dataclasses.dataclass(frozen=False)
class ManagedWarehouseShadowInputs:
    team_id: int
    dag_id: str
    node_id: str
    job_id: str
    dangerously_execute_raw_sql: bool = False
    use_trino: bool = False

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
            "job_id": self.job_id,
        }


INCREMENTAL_RUN_MODE = DataModelingJobRunMode.INCREMENTAL.value
FULL_REFRESH_RUN_MODE = DataModelingJobRunMode.FULL_REFRESH.value


@dataclasses.dataclass(frozen=False)
class ManagedWarehouseShadowResult:
    row_count: int
    duration_seconds: float
    schema_name: str
    table_name: str
    error: str | None = None
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0
    run_mode: str = UNKNOWN_RUN_MODE
    read_bytes: int | None = None
    cpu_microseconds: int | None = None
    # The run read an upstream model that has never been built on Trino. That says nothing about the
    # view itself, so the job is skipped rather than failed and does not count toward suspension.
    skipped: bool = False


_TABLE_MISSING_ERROR_NAMES = frozenset({"CATALOG_NOT_FOUND", "SCHEMA_NOT_FOUND", "TABLE_NOT_FOUND"})


def _upstream_model_unbuilt(missing_object_error_name: str | None, team_id: int, saved_query_id: UUID) -> bool:
    """Whether a missing Trino table is explained by an upstream model that has never been built there.

    A missing imported table or events table is a sync or provisioning fault, so it still fails the job.
    """
    if missing_object_error_name not in _TABLE_MISSING_ERROR_NAMES:
        return False
    return bool(
        unbuilt_upstream_saved_query_ids(team_id, saved_query_id, engine=DataModelingJobEngine.MANAGED_WAREHOUSE)
    )


def _failed_run_mode(plan: WritePlan | None, use_trino: bool) -> str:
    if not use_trino:
        return FULL_REFRESH_RUN_MODE
    if plan is None:
        return UNKNOWN_RUN_MODE
    return INCREMENTAL_RUN_MODE if plan.incremental else FULL_REFRESH_RUN_MODE


@frozen
class _ManagedWarehouseShadowObjects:
    team: Team
    node: Node
    saved_query: DataWarehouseSavedQuery


def _is_managed_warehouse_shadow_flag_enabled(team: Team) -> bool:
    if is_dev_mode():
        return os.environ.get("MANAGED_WAREHOUSE_SHADOW_ENABLED", "").lower() in ("1", "true")

    if not has_provisioned_warehouse(str(team.organization_id)):
        return False

    try:
        return feature_enabled_or_false(
            FEATURE_FLAG,
            str(team.pk),
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
    except Exception:
        return False


def is_managed_warehouse_shadow_enabled(team: Team) -> bool:
    if not _is_managed_warehouse_shadow_flag_enabled(team):
        return False

    return is_data_modeling_shadow_ready(
        organization_id=team.organization_id,
        team_id=team.pk,
    )


def _compile_hogql_for_ducklake(hogql_query: str, team_id: int) -> DuckLakeCompiledQuery:
    from posthog.schema import HogQLQuery

    from products.managed_warehouse.backend.facade.client import compile_hogql_to_ducklake_sql

    return compile_hogql_to_ducklake_sql(
        team_id,
        HogQLQuery(query=hogql_query),
        # Userless shadow materialization; mirror ClickHouse materialization so the
        # model query can resolve its warehouse source tables/views.
        bypass_warehouse_access_control=True,
    )


def _load_shadow_objects(*, team_id: int, dag_id: str, node_id: str) -> _ManagedWarehouseShadowObjects:
    team = Team.objects.get(id=team_id)
    node = Node.objects.prefetch_related("saved_query").get(id=node_id, team_id=team_id, dag_id=dag_id)
    if node.type == NodeType.TABLE or node.saved_query is None:
        raise ValueError(f"Node {node.name} is not materializable")
    saved_query = DataWarehouseSavedQuery.objects.exclude(deleted=True).get(id=node.saved_query.id, team_id=team_id)

    return _ManagedWarehouseShadowObjects(team=team, node=node, saved_query=saved_query)


@database_sync_to_async_pool
def _get_shadow_input_objects(inputs: ManagedWarehouseShadowInputs) -> _ManagedWarehouseShadowObjects:
    objects = _load_shadow_objects(team_id=inputs.team_id, dag_id=inputs.dag_id, node_id=inputs.node_id)
    saved_query = objects.saved_query
    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        prepare_executable_query(saved_query)

    return objects


@database_sync_to_async_pool
def _check_managed_warehouse_shadow_eligibility(inputs: ManagedWarehouseShadowEligibilityInputs) -> bool:
    objects = _load_shadow_objects(team_id=inputs.team_id, dag_id=inputs.dag_id, node_id=inputs.node_id)
    return is_managed_warehouse_shadow_enabled(objects.team)


async def _check_managed_warehouse_shadow_enabled_activity(team_id: int) -> bool:
    """Check the legacy team-level shadow prerequisites."""
    team = await database_sync_to_async_pool(Team.objects.get)(id=team_id)
    return await database_sync_to_async_pool(_is_managed_warehouse_shadow_flag_enabled)(team)


@activity.defn
async def check_managed_warehouse_shadow_enabled_activity(team_id: int) -> bool:
    return await _check_managed_warehouse_shadow_enabled_activity(team_id)


@database_sync_to_async_pool
def _check_team_managed_warehouse_shadow_eligibility(team_id: int) -> bool:
    return is_managed_warehouse_shadow_enabled(Team.objects.get(id=team_id))


@activity.defn
async def check_team_managed_warehouse_shadow_eligibility_activity(team_id: int) -> bool:
    """Check whether DAG runs of this team's organization should start a Trino shadow run."""
    return await _check_team_managed_warehouse_shadow_eligibility(team_id)


@activity.defn
async def check_managed_warehouse_shadow_eligibility_activity(
    inputs: ManagedWarehouseShadowEligibilityInputs,
) -> bool:
    """Check whether the managed warehouse shadow path is eligible to run."""
    return await _check_managed_warehouse_shadow_eligibility(inputs)


@database_sync_to_async_pool
def _resolve_managed_warehouse_job(job_id: str, result: "ManagedWarehouseShadowResult") -> str:
    """Update the managed warehouse job to its terminal state based on the result."""
    job = DataModelingJob.objects.get(id=job_id)
    if job.status in TERMINAL_JOB_STATUSES:
        return job.engine
    if result.error is None:
        job.status = DataModelingJobStatus.COMPLETED
        job.rows_materialized = result.row_count
        job.error = None
    elif result.skipped:
        job.status = DataModelingJobStatus.SKIPPED
        job.rows_materialized = 0
        job.error = result.error
    else:
        job.status = DataModelingJobStatus.FAILED
        job.rows_materialized = 0
        job.error = result.error
    completed_at = dt.datetime.now(dt.UTC)
    job.read_bytes = result.read_bytes
    job.cpu_microseconds = result.cpu_microseconds
    job.usage_updated_at = (
        completed_at if result.read_bytes is not None or result.cpu_microseconds is not None else None
    )
    job.last_run_at = completed_at
    job.save()
    return job.engine


async def _materialize_view_managed_warehouse(
    inputs: ManagedWarehouseShadowInputs,
) -> ManagedWarehouseShadowResult:
    """Shadow activity: execute a managed warehouse materialization and create a DuckLake table.

    It runs in a managed_warehouse_only MaterializeViewWorkflow, which the Trino shadow DAG run
    starts separately from the ClickHouse run, so its failures never affect ClickHouse.
    The query result is materialized as a native DuckLake table (Parquet on S3 + Postgres catalog).
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    objects = await _get_shadow_input_objects(inputs)
    team = objects.team
    node = objects.node
    saved_query = objects.saved_query
    bind_data_modeling_log_context(inputs.team_id, saved_query.id)
    schema_name = ducklake_data_modeling_schema(team.pk) if inputs.use_trino else duckgres_data_modeling_schema(team.pk)
    table_name = "" if inputs.use_trino else saved_query.normalized_name

    start_time = time.monotonic()
    sql: str = ""
    values: dict[str, object] = {}
    s3_secrets: tuple[DuckLakeS3Secret, ...] = ()
    plan: WritePlan | None = None
    processed_bytes: list[int] = []
    cpu_milliseconds: list[int] = []
    try:
        from products.managed_warehouse.backend.facade.client import execute_ducklake_create_table, execute_trino_model

        if inputs.use_trino:
            table_name = await database_sync_to_async_pool(get_data_modeling_table_name)(team.pk, saved_query.id)
        await logger.ainfo(
            "Starting managed warehouse shadow materialization",
            node_name=node.name,
            schema_name=schema_name,
            table_name=table_name,
        )
        if inputs.use_trino:
            plan = await database_sync_to_async_pool(resolve_write_plan)(
                team.pk, saved_query.id, scope=TRINO_INCREMENTAL_SCOPE
            )
            await logger.ainfo("Trino write plan", incremental=plan.incremental, reason=plan.reason)
            result = await execute_trino_model(
                organization_id=str(team.organization_id),
                team_id=team.pk,
                saved_query_id=saved_query.id,
                source_query=saved_query.query,
                incremental=_trino_incremental_write(plan),
                on_processed_bytes=processed_bytes.append,
                on_cpu_milliseconds=cpu_milliseconds.append,
            )
            if plan.config is not None:
                # A quiet window writes nothing, so it records the run without moving the watermark.
                await database_sync_to_async_pool(set_incremental_state)(
                    saved_query,
                    watermark=result.watermark,
                    fingerprint=plan.fingerprint,
                    mode="incremental" if result.merged else "full_refresh",
                    scope=TRINO_INCREMENTAL_SCOPE,
                )
            from products.managed_warehouse.backend.facade.client import request_model_alias_reconciliation

            try:
                await request_model_alias_reconciliation(team.pk, str(saved_query.id))
            except Exception as error:
                capture_exception(error)
                await logger.awarning(
                    "Could not schedule Trino model aliases; retry alias reconciliation without rebuilding the model",
                    team_id=team.pk,
                )
        else:
            hogql_query = typing.cast(dict, saved_query.query)["query"]
            if inputs.dangerously_execute_raw_sql:
                sql = hogql_query
            else:
                compiled = await database_sync_to_async_pool(_compile_hogql_for_ducklake)(hogql_query, team.pk)
                sql = compiled.sql
                values = compiled.values
                s3_secrets = compiled.s3_secrets
            await logger.adebug("Managed warehouse shadow SQL generated", sql=sql)
            result = await database_sync_to_async_pool(execute_ducklake_create_table)(
                team.pk, sql, schema_name, table_name, values, s3_secrets=s3_secrets
            )
        duration = time.monotonic() - start_time

        await logger.ainfo(
            "Managed warehouse shadow materialization completed",
            node_name=node.name,
            row_count=result.row_count,
            duration_seconds=round(duration, 2),
            schema_name=result.schema_name,
            table_name=result.table_name,
        )

        shadow_result = ManagedWarehouseShadowResult(
            row_count=result.row_count,
            duration_seconds=duration,
            schema_name=result.schema_name,
            table_name=result.table_name,
            file_size_bytes=result.file_size_bytes,
            file_size_delta_bytes=result.file_size_delta_bytes,
            run_mode=INCREMENTAL_RUN_MODE if inputs.use_trino and result.merged else FULL_REFRESH_RUN_MODE,
            read_bytes=_total_read_bytes(processed_bytes),
            cpu_microseconds=_total_cpu_microseconds(cpu_milliseconds),
        )
        job_engine = await _resolve_managed_warehouse_job(inputs.job_id, shadow_result)
        await clear_node_suspension_for_engine(
            node_id=inputs.node_id,
            team_id=inputs.team_id,
            dag_id=inputs.dag_id,
            engine=job_engine,
        )
        return shadow_result
    except Exception as e:
        from products.managed_warehouse.backend.facade.client import get_trino_missing_object_error_name

        duration = time.monotonic() - start_time
        missing_object_error_name = get_trino_missing_object_error_name(e)
        if isinstance(e, TrinoLoweringError):
            # Unsupported HogQL is an expected shadow outcome, so it is not an exception to track.
            get_managed_warehouse_trino_compile_failure_metric(e.feature_code).add(1)
            await logger.awarning(
                "Managed warehouse shadow could not compile the view for Trino",
                node_name=node.name,
                error_code=e.feature_code,
                duration_seconds=round(duration, 2),
            )
        elif missing_object_error_name is not None:
            # A column or table that Trino cannot resolve is an expected shadow outcome, so it is not an exception to track.
            get_managed_warehouse_trino_missing_object_metric(missing_object_error_name).add(1)
            await logger.awarning(
                "Managed warehouse shadow query failed in Trino",
                node_name=node.name,
                error_name=missing_object_error_name,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
        else:
            capture_exception(e, {"sql": sql, "inputs": inputs})
            await logger.awarning(
                "Managed warehouse shadow materialization failed",
                node_name=node.name,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
        shadow_result = ManagedWarehouseShadowResult(
            row_count=0,
            duration_seconds=duration,
            schema_name=schema_name,
            table_name=table_name,
            error=str(e),
            run_mode=_failed_run_mode(plan, inputs.use_trino),
            read_bytes=_total_read_bytes(processed_bytes),
            cpu_microseconds=_total_cpu_microseconds(cpu_milliseconds),
            skipped=await database_sync_to_async_pool(_upstream_model_unbuilt)(
                missing_object_error_name, team.pk, saved_query.id
            ),
        )
        if plan is not None and plan.incremental:
            # The merge may have stopped partway or failed on a schema change. Rebuilding next run
            # is the only state that is certainly correct.
            try:
                await database_sync_to_async_pool(clear_incremental_state)(saved_query, scope=TRINO_INCREMENTAL_SCOPE)
            except Exception as clear_error:
                capture_exception(clear_error)
        job_engine = await _resolve_managed_warehouse_job(inputs.job_id, shadow_result)
        if shadow_result.skipped:
            return shadow_result
        suspended = await maybe_suspend_node_for_engine(
            node_id=inputs.node_id,
            team_id=inputs.team_id,
            dag_id=inputs.dag_id,
            saved_query_id=saved_query.id,
            engine=job_engine,
            reason=str(e),
            job_id=inputs.job_id,
        )
        if suspended:
            get_node_suspended_metric(job_engine).add(1)
            await logger.ainfo(
                f"Suspended node {inputs.node_id} ({job_engine}) after {CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failures",
            )
        return shadow_result


def _total_read_bytes(processed_bytes: list[int]) -> int | None:
    # No statement reported its bytes, so the run was not measured. That is not the same as reading zero bytes.
    return sum(processed_bytes) if processed_bytes else None


def _total_cpu_microseconds(cpu_milliseconds: list[int]) -> int | None:
    return sum(cpu_milliseconds) * 1_000 if cpu_milliseconds else None


def _trino_incremental_write(plan: WritePlan) -> TrinoIncrementalWrite | None:
    if plan.config is None:
        return None
    return TrinoIncrementalWrite(
        incremental_key=plan.config.incremental_key,
        unique_key=tuple(plan.config.unique_key),
        since=plan.since if plan.incremental else None,
    )


@activity.defn
async def materialize_view_managed_warehouse_activity(
    inputs: ManagedWarehouseShadowInputs,
) -> ManagedWarehouseShadowResult:
    if inputs.use_trino:
        async with Heartbeater():
            return await _materialize_view_managed_warehouse(inputs)
    return await _materialize_view_managed_warehouse(inputs)
