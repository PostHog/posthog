import time
import typing
import datetime as dt
import dataclasses

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.ducklake.common import duckgres_data_modeling_schema, get_duckgres_server_for_organization, is_dev_mode
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)
from products.endpoints.backend.facade.temporal import prepare_executable_query

from ..metrics import get_node_suspended_metric
from .utils import CONSECUTIVE_FAILURES_TO_SUSPEND, clear_node_suspension_for_engine, maybe_suspend_node_for_engine

LOGGER = get_logger(__name__)

FEATURE_FLAG = "duckgres-data-modeling-shadow"


@dataclasses.dataclass
class DuckgresShadowInputs:
    team_id: int
    dag_id: str
    node_id: str
    job_id: str
    dangerously_execute_raw_sql: bool = False

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
            "job_id": self.job_id,
        }


@dataclasses.dataclass
class DuckgresShadowResult:
    row_count: int
    duration_seconds: float
    schema_name: str
    table_name: str
    error: str | None = None
    file_size_bytes: int = 0
    file_size_delta_bytes: int = 0


def _is_duckgres_shadow_enabled(team: Team) -> bool:
    if is_dev_mode():
        import os

        return os.environ.get("DUCKGRES_SHADOW_ENABLED", "").lower() in ("1", "true")

    if get_duckgres_server_for_organization(str(team.organization_id)) is None:
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


def _compile_hogql_to_postgres_sql(hogql_query: str, team_id: int) -> tuple[str, dict[str, object]]:
    from posthog.schema import HogQLQuery

    from posthog.ducklake.client import compile_hogql_to_ducklake_sql

    postgres_sql, values, _ = compile_hogql_to_ducklake_sql(
        team_id,
        HogQLQuery(query=hogql_query),
        # Userless shadow materialization; mirror ClickHouse materialization so the
        # model query can resolve its warehouse source tables/views.
        bypass_warehouse_access_control=True,
    )
    return postgres_sql, values


@database_sync_to_async_pool
def _get_shadow_input_objects(
    inputs: DuckgresShadowInputs,
) -> tuple[Team, Node, DataWarehouseSavedQuery]:
    team = Team.objects.get(id=inputs.team_id)
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id
    )
    if node.type == NodeType.TABLE or node.saved_query is None:
        raise ValueError(f"Node {node.name} is not materializable")
    saved_query = DataWarehouseSavedQuery.objects.exclude(deleted=True).get(
        id=node.saved_query.id, team_id=inputs.team_id
    )
    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        prepare_executable_query(saved_query)

    return (team, node, saved_query)


@activity.defn
async def check_duckgres_shadow_enabled_activity(team_id: int) -> bool:
    """Check whether the duckgres shadow flag is enabled for a team."""
    team = await database_sync_to_async_pool(Team.objects.get)(id=team_id)
    return await database_sync_to_async_pool(_is_duckgres_shadow_enabled)(team)


@database_sync_to_async_pool
def _resolve_duckgres_job(job_id: str, result: "DuckgresShadowResult") -> None:
    """Update the duckgres job to its terminal state based on the result."""
    job = DataModelingJob.objects.get(id=job_id)
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return
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


@activity.defn
async def materialize_view_duckgres_activity(inputs: DuckgresShadowInputs) -> DuckgresShadowResult:
    """Shadow activity: execute materialization query via duckgres and create a DuckLake table.

    This is a fire-and-forget companion to the main ClickHouse-based materialize_view_activity.
    The query result is materialized as a native DuckLake table (Parquet on S3 + Postgres catalog).
    Failures here never affect the parent workflow.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    team, node, saved_query = await _get_shadow_input_objects(inputs)
    hogql_query = typing.cast(dict, saved_query.query)["query"]
    schema_name = duckgres_data_modeling_schema(team.pk)
    table_name = saved_query.normalized_name

    await logger.ainfo(
        "Starting duckgres shadow materialization",
        node_name=node.name,
        schema_name=schema_name,
        table_name=table_name,
    )

    start_time = time.monotonic()
    sql: str = ""
    values: dict[str, object] = {}
    try:
        if inputs.dangerously_execute_raw_sql:
            sql = hogql_query
        else:
            sql, values = await database_sync_to_async_pool(_compile_hogql_to_postgres_sql)(hogql_query, team.pk)
        await logger.adebug("Duckgres shadow SQL generated", sql=sql)

        from posthog.ducklake.client import execute_ducklake_create_table

        result = await database_sync_to_async_pool(execute_ducklake_create_table)(
            team.pk, sql, schema_name, table_name, values
        )
        duration = time.monotonic() - start_time

        await logger.ainfo(
            "Duckgres shadow materialization completed",
            node_name=node.name,
            row_count=result.row_count,
            duration_seconds=round(duration, 2),
            schema_name=result.schema_name,
            table_name=result.table_name,
        )

        shadow_result = DuckgresShadowResult(
            row_count=result.row_count,
            duration_seconds=duration,
            schema_name=result.schema_name,
            table_name=result.table_name,
            file_size_bytes=result.file_size_bytes,
            file_size_delta_bytes=result.file_size_delta_bytes,
        )
        await _resolve_duckgres_job(inputs.job_id, shadow_result)
        await clear_node_suspension_for_engine(
            node_id=inputs.node_id,
            team_id=inputs.team_id,
            dag_id=inputs.dag_id,
            engine=DataModelingJobEngine.DUCKGRES,
        )
        return shadow_result
    except Exception as e:
        duration = time.monotonic() - start_time
        capture_exception(e, {"sql": sql, "inputs": inputs})
        await logger.awarning(
            "Duckgres shadow materialization failed",
            node_name=node.name,
            error=str(e),
            duration_seconds=round(duration, 2),
        )
        shadow_result = DuckgresShadowResult(
            row_count=0,
            duration_seconds=duration,
            schema_name=schema_name,
            table_name=table_name,
            error=str(e),
        )
        await _resolve_duckgres_job(inputs.job_id, shadow_result)
        suspended = await maybe_suspend_node_for_engine(
            node_id=inputs.node_id,
            team_id=inputs.team_id,
            dag_id=inputs.dag_id,
            saved_query_id=saved_query.id,
            engine=DataModelingJobEngine.DUCKGRES,
            reason=str(e),
            job_id=inputs.job_id,
        )
        if suspended:
            get_node_suspended_metric(DataModelingJobEngine.DUCKGRES.value).add(1)
            await logger.ainfo(
                f"Suspended node {inputs.node_id} (duckgres) after {CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failures",
            )
        return shadow_result
