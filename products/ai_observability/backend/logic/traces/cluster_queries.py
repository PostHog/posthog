import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.temporal.ai_observability.trace_clustering.constants import DEFAULT_LOOKBACK_DAYS, EVENT_NAME

from products.access_control.backend.facade.user_access_control import UserAccessControl

CLUSTER_RUNS_LIMIT = 100
# Runs pick items by when their summary was embedded, so a run can list a trace long after the trace started.
# The embedding lands within a day of the trace, a scheduled run looks back DEFAULT_LOOKBACK_DAYS from its end,
# and the run is emitted within an hour of its end. The reach covers that sum with most of a day to spare.
CLUSTER_RUN_REACH = timedelta(days=DEFAULT_LOOKBACK_DAYS + 2)
# Every JSON serializer on the write and read paths writes these characters verbatim, so the raw text contains the id.
_VERBATIM_SAFE_ID = re.compile(r"[A-Za-z0-9_:-]+")


@frozen
class ClusterRunWindow:
    start: datetime
    end: datetime

    @classmethod
    def for_trace(cls, created_at: datetime) -> Self:
        start = created_at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(start=start, end=created_at + CLUSTER_RUN_REACH)


@frozen
class ClusterRunRow:
    uuid: str
    timestamp: datetime
    run_id: str | None
    job_id: str | None
    job_name: str | None
    clusters: str | None


def _property(name: str) -> ast.Field:
    return ast.Field(chain=["properties", name])


def _runs_query(trace_id: str, window: ClusterRunWindow) -> ast.SelectQuery:
    conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=EVENT_NAME),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=window.start)
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=window.end)
        ),
    ]
    if _VERBATIM_SAFE_ID.fullmatch(trace_id):
        # A substring check skips parsing runs that cannot list the trace; membership is decided after parsing.
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Call(name="position", args=[_property("$ai_clusters"), ast.Constant(value=trace_id)]),
                right=ast.Constant(value=0),
            )
        )
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["uuid"]),
            ast.Field(chain=["timestamp"]),
            _property("$ai_clustering_run_id"),
            _property("$ai_clustering_job_id"),
            _property("$ai_clustering_job_name"),
            _property("$ai_clusters"),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=conditions),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=CLUSTER_RUNS_LIMIT),
    )


def _raw(value: Any) -> str | None:
    return None if value is None else str(value)


def _run_row(values: Sequence[Any]) -> ClusterRunRow:
    uuid, timestamp, run_id, job_id, job_name, clusters = values
    return ClusterRunRow(
        uuid=str(uuid),
        timestamp=timestamp,
        run_id=_raw(run_id),
        job_id=_raw(job_id),
        job_name=_raw(job_name),
        clusters=_raw(clusters),
    )


def load_cluster_runs(
    team: Team, user: User | None, trace_id: str, window: ClusterRunWindow
) -> tuple[ClusterRunRow, ...]:
    name = "ai_trace_clusters"
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=_runs_query(trace_id, window),
            team=team,
            user=user,
            query_type=name,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
        )
    return tuple(_run_row(values) for values in response.results or [])


def can_read_clusters(team: Team, user: User | None) -> bool:
    # Clusters have their own access control, apart from the llm_analytics access that opens the trace.
    return user is None or UserAccessControl(user=user, team=team).check_access_level_for_resource(
        "ai_observability_clusters", "viewer"
    )
