import time
import typing
import dataclasses

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.ducklake.common import get_duckgres_server_for_team, is_dev_mode
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.models import Node, NodeType
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

LOGGER = get_logger(__name__)

FEATURE_FLAG = "duckgres-data-modeling-shadow"
SHADOW_SCHEMA_PREFIX = "shadow"


@dataclasses.dataclass
class DuckgresShadowInputs:
    team_id: int
    dag_id: str
    node_id: str
    job_id: str

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


def _is_duckgres_shadow_enabled(team: Team) -> bool:
    if is_dev_mode():
        import os

        return os.environ.get("DUCKGRES_SHADOW_ENABLED", "").lower() in ("1", "true")

    if get_duckgres_server_for_team(team.id) is None:
        return False

    try:
        return posthoganalytics.feature_enabled(
            FEATURE_FLAG,
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
    except Exception:
        return False


def _compile_hogql_to_postgres_sql(hogql_query: str, team_id: int) -> str:
    from posthog.schema import HogQLQuery

    from posthog.ducklake.client import compile_hogql_to_ducklake_sql

    postgres_sql, _ = compile_hogql_to_ducklake_sql(team_id, HogQLQuery(query=hogql_query))
    return postgres_sql


@database_sync_to_async
def _get_shadow_input_objects(
    inputs: DuckgresShadowInputs,
) -> tuple[Team, Node, DataWarehouseSavedQuery]:
    team = Team.objects.get(id=inputs.team_id)
    node = Node.objects.prefetch_related("saved_query").get(
        id=inputs.node_id, team_id=inputs.team_id, dag_id_text=inputs.dag_id
    )
    if node.type == NodeType.TABLE or node.saved_query is None:
        raise ValueError(f"Node {node.name} is not materializable")
    saved_query = DataWarehouseSavedQuery.objects.exclude(deleted=True).get(
        id=node.saved_query.id, team_id=inputs.team_id
    )
    return (team, node, saved_query)


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

    if not await database_sync_to_async(_is_duckgres_shadow_enabled)(team):
        await logger.ainfo("Duckgres shadow disabled for team", extra=inputs.properties_to_log)
        return DuckgresShadowResult(row_count=0, duration_seconds=0.0, schema_name="", table_name="", error="disabled")

    hogql_query = typing.cast(dict, saved_query.query)["query"]
    schema_name = f"{SHADOW_SCHEMA_PREFIX}_{team.pk}_models"
    table_name = saved_query.normalized_name

    await logger.ainfo(
        "Starting duckgres shadow materialization",
        node_name=node.name,
        schema_name=schema_name,
        table_name=table_name,
    )

    start_time = time.monotonic()
    try:
        sql = await database_sync_to_async(_compile_hogql_to_postgres_sql)(hogql_query, team.pk)
        await logger.adebug("Duckgres shadow SQL generated", sql=sql)

        from posthog.ducklake.client import execute_ducklake_create_table

        result = await database_sync_to_async(execute_ducklake_create_table)(team.pk, sql, schema_name, table_name)
        duration = time.monotonic() - start_time

        await logger.ainfo(
            "Duckgres shadow materialization completed",
            node_name=node.name,
            row_count=result.row_count,
            duration_seconds=round(duration, 2),
            schema_name=result.schema_name,
            table_name=result.table_name,
        )

        return DuckgresShadowResult(
            row_count=result.row_count,
            duration_seconds=duration,
            schema_name=result.schema_name,
            table_name=result.table_name,
        )
    except Exception as e:
        duration = time.monotonic() - start_time
        await logger.awarning(
            "Duckgres shadow materialization failed",
            node_name=node.name,
            error=str(e),
            duration_seconds=round(duration, 2),
        )
        return DuckgresShadowResult(
            row_count=0,
            duration_seconds=duration,
            schema_name=schema_name,
            table_name=table_name,
            error=str(e),
        )
