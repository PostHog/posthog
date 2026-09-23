import os
import time
import typing
import datetime as dt
import dataclasses

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
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
from products.managed_warehouse.backend.facade.contracts import DuckLakeCompiledQuery, DuckLakeS3Secret
from products.managed_warehouse.backend.facade.feature_flags import DATA_MODELING_SHADOW_FLAG

from ..metrics import get_node_suspended_metric
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


@dataclasses.dataclass(frozen=False)
class ManagedWarehouseShadowResult:
    row_count: int
    duration_seconds: float
    schema_name: str
    table_name: str
    error: str | None = None
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0


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


def _is_managed_warehouse_shadow_enabled(team: Team, saved_query: DataWarehouseSavedQuery) -> bool:
    if not _is_managed_warehouse_shadow_flag_enabled(team):
        return False

    return is_data_modeling_shadow_ready(
        organization_id=team.organization_id,
        team_id=team.id,
        saved_query_id=saved_query.id,
        source_query=saved_query.query,
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
    return _is_managed_warehouse_shadow_enabled(objects.team, objects.saved_query)


async def _check_managed_warehouse_shadow_enabled_activity(team_id: int) -> bool:
    """Check the legacy team-level shadow prerequisites."""
    team = await database_sync_to_async_pool(Team.objects.get)(id=team_id)
    return await database_sync_to_async_pool(_is_managed_warehouse_shadow_flag_enabled)(team)


@activity.defn
async def check_managed_warehouse_shadow_enabled_activity(team_id: int) -> bool:
    return await _check_managed_warehouse_shadow_enabled_activity(team_id)


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
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return job.engine
    if result.error is None:
        job.status = DataModelingJobStatus.COMPLETED
        job.rows_materialized = result.row_count
        job.error = None
    else:
        job.status = DataModelingJobStatus.FAILED
        job.rows_materialized = 0
        job.error = result.error
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.save()
    return job.engine


async def _materialize_view_managed_warehouse(
    inputs: ManagedWarehouseShadowInputs,
) -> ManagedWarehouseShadowResult:
    """Shadow activity: execute a managed warehouse materialization and create a DuckLake table.

    This is a fire-and-forget companion to the main ClickHouse-based materialize_view_activity.
    The query result is materialized as a native DuckLake table (Parquet on S3 + Postgres catalog).
    Failures here never affect the parent workflow.
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
            result = await execute_trino_model(
                organization_id=str(team.organization_id),
                team_id=team.pk,
                saved_query_id=saved_query.id,
                source_query=saved_query.query,
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
        duration = time.monotonic() - start_time
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
        )
        job_engine = await _resolve_managed_warehouse_job(inputs.job_id, shadow_result)
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


@activity.defn
async def materialize_view_managed_warehouse_activity(
    inputs: ManagedWarehouseShadowInputs,
) -> ManagedWarehouseShadowResult:
    if inputs.use_trino:
        async with Heartbeater():
            return await _materialize_view_managed_warehouse(inputs)
    return await _materialize_view_managed_warehouse(inputs)
