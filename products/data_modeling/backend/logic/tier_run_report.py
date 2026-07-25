"""What each cadence tier of a DAG declares, and what its most recent run actually did.

Answers "the daily tier holds N nodes — did they all run, and if not why not?" from Postgres
alone. `DataModelingJob.parent_workflow_id` carries the tier's schedule id, so a run's job rows
are attributable to the tier that produced them without asking Temporal.

This is deliberately *not* a check that a node is in the live schedule's `node_ids` — that lives
in Temporal, encrypted. A node reported `MISSING` here is either absent from the live tier or was
skipped for a reason the run did not record; distinguishing those needs the Temporal read.
"""

import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import models

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import format_cadence
from products.data_modeling.backend.logic.node_frequency import get_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

# node types a DAG run actually materializes; everything else is skipped and never gets a job row
MATERIALIZING_TYPES = frozenset({NodeType.MAT_VIEW.value, NodeType.ENDPOINT.value})

OK = "ok"
FAILED = "failed"
RUNNING = "running"
CANCELLED = "cancelled"
SUSPENDED = "suspended"
BLOCKED = "blocked"
MISSING = "missing"
NOT_MATERIALIZING = "not_materializing"

# worst first — drives display order within a tier
STATUS_ORDER = (MISSING, FAILED, CANCELLED, SUSPENDED, BLOCKED, RUNNING, NOT_MATERIALIZING, OK)

# only a Completed job proves the node materialized. Jobs default to Running, and a row left
# Running by a dead workflow is only reaped by a later run of the same DAG, so treating anything
# other than Completed as success would paint corpses green.
_JOB_STATUS_TO_NODE_STATUS = {
    DataModelingJobStatus.COMPLETED.value: OK,
    DataModelingJobStatus.FAILED.value: FAILED,
    DataModelingJobStatus.RUNNING.value: RUNNING,
    DataModelingJobStatus.CANCELLED.value: CANCELLED,
}


@dataclasses.dataclass(frozen=True)
class NodeRun:
    node_id: str
    name: str
    node_type: str
    saved_query_id: str | None
    status: str
    detail: str
    job_id: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None


@dataclasses.dataclass(frozen=True)
class TierRun:
    interval: timedelta
    schedule_id: str
    parent_workflow_id: str | None
    started_at: datetime | None
    nodes: list[NodeRun]
    # the matched run came from the DAG's pre-tier single schedule, not from this tier's own
    run_is_legacy: bool = False

    @property
    def label(self) -> str:
        return format_cadence(self.interval)

    @property
    def seconds(self) -> int:
        """Anchor-safe tier identifier; `schedule_id` carries a colon."""
        return int(self.interval.total_seconds())

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(STATUS_ORDER, 0)
        for node in self.nodes:
            counts[node.status] += 1
        return counts

    @property
    def declared(self) -> int:
        """Nodes on this tier a run is expected to materialize."""
        return sum(1 for node in self.nodes if node.node_type in MATERIALIZING_TYPES)

    @property
    def ran(self) -> int:
        return sum(1 for node in self.nodes if node.job_id is not None)


def build_tier_runs(dag: DAG) -> list[TierRun]:
    """One TierRun per declared cadence on `dag`, finest cadence first."""
    nodes = _reportable_nodes(dag)
    nodes_by_interval: dict[timedelta, list[Node]] = defaultdict(list)
    for node in nodes:
        target = get_declared_target(node)
        if target is not None:
            nodes_by_interval[target].append(node)

    downstream = _downstream_lookup(dag)
    # the runtime blocks on suspension DAG-wide, not per tier: get_dag_structure builds
    # suspended_nodes over every executable node, so a suspended node in the daily tier skips its
    # descendants in the hourly one. Seeding only from this tier would report those as unexplained.
    suspensions = {str(node.id): _suspension_detail(node) for node in nodes}
    names = {str(node.id): node.name for node in nodes}
    return [
        _build_tier(dag, interval, nodes_by_interval[interval], downstream, suspensions, names)
        for interval in sorted(nodes_by_interval)
    ]


def untargeted_nodes(dag: DAG) -> list[Node]:
    """Nodes carrying no declared target — they belong to no tier, so no schedule fires them."""
    return [node for node in _reportable_nodes(dag) if get_declared_target(node) is None]


def _reportable_nodes(dag: DAG) -> list[Node]:
    """Every node a run could act on. Mirrors `schedulable_nodes`' exclusion of soft-deleted saved
    queries — those keep their target but the scheduler never sees them, so reporting them would
    manufacture permanent phantom rows. Source (TABLE) nodes are kept so the page can show them.
    """
    return list(
        Node.objects.filter(team_id=dag.team_id, dag=dag)
        .exclude(saved_query__deleted=True)
        .select_related("saved_query")
    )


def _build_tier(
    dag: DAG,
    interval: timedelta,
    nodes: list[Node],
    downstream: dict[str, set[str]],
    suspensions: dict[str, str],
    names: dict[str, str],
) -> TierRun:
    schedule_id = tier_schedule_id(str(dag.id), interval)
    parent_workflow_id, started_at, run_is_legacy = _latest_run(dag.team_id, str(dag.id), schedule_id)
    jobs = _jobs_by_saved_query(dag.team_id, parent_workflow_id)

    blocked_seeds = {node_id for node_id, suspension in suspensions.items() if suspension}
    for node in nodes:
        job = jobs.get(str(node.saved_query_id)) if node.saved_query_id else None
        if job is not None and job.status == DataModelingJobStatus.FAILED:
            blocked_seeds.add(str(node.id))

    # execute_dag skips a node whose ancestor failed or is suspended, so attribute those before
    # calling anything unexplained
    blocked_by: dict[str, str] = {}
    for seed in blocked_seeds:
        for descendant in downstream.get(seed, ()):
            blocked_by.setdefault(descendant, seed)

    runs = [
        _node_run(
            node,
            job=jobs.get(str(node.saved_query_id)) if node.saved_query_id else None,
            suspension=suspensions[str(node.id)],
            blocked_by=names.get(blocked_by.get(str(node.id), ""), blocked_by.get(str(node.id), "")),
        )
        for node in nodes
    ]
    runs.sort(key=lambda run: (STATUS_ORDER.index(run.status), run.name))
    return TierRun(
        interval=interval,
        schedule_id=schedule_id,
        parent_workflow_id=parent_workflow_id,
        started_at=started_at,
        nodes=runs,
        run_is_legacy=run_is_legacy,
    )


def _node_run(node: Node, *, job: DataModelingJob | None, suspension: str, blocked_by: str) -> NodeRun:
    def run(status: str, detail: str, job: DataModelingJob | None = None) -> NodeRun:
        return NodeRun(
            node_id=str(node.id),
            name=node.name,
            node_type=node.type,
            saved_query_id=str(node.saved_query_id) if node.saved_query_id else None,
            status=status,
            detail=detail,
            job_id=str(job.id) if job else None,
            workflow_id=job.workflow_id if job else None,
            workflow_run_id=job.workflow_run_id if job else None,
        )

    if node.type not in MATERIALIZING_TYPES:
        return run(
            NOT_MATERIALIZING,
            "view node — a run marks it successful and materializes nothing"
            if node.type == NodeType.VIEW.value
            else "source node — nothing to materialize",
        )

    if job is not None:
        status = _JOB_STATUS_TO_NODE_STATUS.get(job.status, FAILED)
        detail = _first_line(job.error) or f"{job.rows_materialized or 0} rows"
        if status == RUNNING:
            detail = "still running, or a row left behind by a dead workflow"
        return run(status, detail, job)

    if suspension:
        return run(SUSPENDED, suspension)
    if blocked_by:
        return run(BLOCKED, f"upstream {blocked_by} failed or is suspended")
    return run(MISSING, "declared on this tier but the run produced no job")


def _latest_run(team_id: int, dag_id: str, schedule_id: str) -> tuple[str | None, datetime | None, bool]:
    """The most recent run whose jobs describe this tier, and whether it came from the legacy schedule.

    A DAG that has not been reconciled onto tiers still runs everything under the single pre-tier
    schedule `execute-dag-{dag_id}`, whose runs no tier prefix can match (a tier id continues with
    `:`, never `-`). Without the fallback every node on such a DAG reports as never having run,
    which is the opposite of the truth for most of the fleet.
    """
    tier = _latest_run_for_prefix(team_id, f"execute-dag-{schedule_id}-")
    if tier is not None:
        return *tier, False
    legacy = _latest_run_for_prefix(team_id, f"execute-dag-{dag_id}-")
    if legacy is not None:
        return *legacy, True
    return None, None, False


def _latest_run_for_prefix(team_id: int, prefix: str) -> tuple[str, datetime] | None:
    """The newest run under `prefix`, identified by its newest job.

    Sound because both schedule-creation sites set `ScheduleOverlapPolicy.SKIP`, so one schedule
    never has two runs in flight and consecutive runs' job timestamps cannot interleave.
    """
    latest = (
        DataModelingJob.objects.filter(team_id=team_id, parent_workflow_id__startswith=prefix)
        .order_by("-created_at")
        .values("parent_workflow_id", "created_at")
        .first()
    )
    if latest is None or latest["parent_workflow_id"] is None:
        return None
    parent_workflow_id: str = latest["parent_workflow_id"]
    # the run's own start, not the last child's — a wide DAG starts children over a long window
    started_at = DataModelingJob.objects.filter(team_id=team_id, parent_workflow_id=parent_workflow_id).aggregate(
        first=models.Min("created_at")
    )["first"]
    return parent_workflow_id, started_at or latest["created_at"]


def _jobs_by_saved_query(team_id: int, parent_workflow_id: str | None) -> dict[str, DataModelingJob]:
    if parent_workflow_id is None:
        return {}
    # the duckgres shadow writes its own row per node in the same run; the serving engine is the
    # one a reader cares about, so filter rather than relying on which row was written last
    return {
        str(job.saved_query_id): job
        for job in DataModelingJob.objects.filter(
            team_id=team_id, parent_workflow_id=parent_workflow_id, engine=DataModelingJobEngine.CLICKHOUSE
        ).order_by("created_at")
    }


def _downstream_lookup(dag: DAG) -> dict[str, set[str]]:
    """Transitive descendants per node, mirroring how execute_dag propagates a block."""
    children: dict[str, list[str]] = defaultdict(list)
    for source_id, target_id in Edge.objects.filter(team_id=dag.team_id, dag=dag).values_list("source_id", "target_id"):
        children[str(source_id)].append(str(target_id))

    downstream: dict[str, set[str]] = {}
    for node_id in children:
        seen: set[str] = set()
        queue = list(children[node_id])
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(children.get(current, ()))
        downstream[node_id] = seen
    return downstream


def _suspension_detail(node: Node) -> str:
    """Why the serving engine skips this node, if it does.

    Only the serving engine's marker blocks a run (`execute_dag` reads one engine's list), and the
    duckgres shadow suspends independently and often — reporting its marker would turn healthy
    nodes and their whole subtree into false `suspended` / `blocked` rows. Note a marker is written
    whether or not `data-modeling-suspend-failing-nodes` is on for the team, so on a team without
    that flag a marker here is decorative and the node still runs.
    """
    suspended = ((node.properties or {}).get("system") or {}).get("suspended") or {}
    entry = suspended.get(DataModelingJobEngine.CLICKHOUSE.value)
    return (entry or {}).get("reason", "unknown") if entry else ""


def _first_line(error: str | None) -> str:
    lines = (error or "").strip().splitlines()
    return lines[0] if lines else ""
