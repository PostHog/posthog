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

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import format_cadence
from products.data_modeling.backend.logic.node_frequency import get_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob, DataModelingJobStatus
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

# node types a DAG run actually materializes; everything else is skipped and never gets a job row
MATERIALIZING_TYPES = frozenset({NodeType.MAT_VIEW.value, NodeType.ENDPOINT.value})

OK = "ok"
FAILED = "failed"
SUSPENDED = "suspended"
BLOCKED = "blocked"
MISSING = "missing"
NOT_MATERIALIZING = "not_materializing"

# worst first — drives display order within a tier
STATUS_ORDER = (MISSING, FAILED, SUSPENDED, BLOCKED, NOT_MATERIALIZING, OK)


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

    @property
    def is_clean(self) -> bool:
        counts = self.counts
        return counts[MISSING] == 0 and counts[FAILED] == 0 and counts[SUSPENDED] == 0


def build_tier_runs(dag: DAG) -> list[TierRun]:
    """One TierRun per declared cadence on `dag`, finest cadence first."""
    nodes_by_interval: dict[timedelta, list[Node]] = defaultdict(list)
    for node in Node.objects.filter(team_id=dag.team_id, dag=dag).select_related("saved_query"):
        target = get_declared_target(node)
        if target is not None:
            nodes_by_interval[target].append(node)

    downstream = _downstream_lookup(dag)
    return [
        _build_tier(dag, interval, nodes_by_interval[interval], downstream) for interval in sorted(nodes_by_interval)
    ]


def untargeted_nodes(dag: DAG) -> list[Node]:
    """Nodes carrying no declared target — they belong to no tier, so no schedule fires them."""
    return [
        node
        for node in Node.objects.filter(team_id=dag.team_id, dag=dag).select_related("saved_query")
        if get_declared_target(node) is None
    ]


def _build_tier(dag: DAG, interval: timedelta, nodes: list[Node], downstream: dict[str, set[str]]) -> TierRun:
    schedule_id = tier_schedule_id(str(dag.id), interval)
    parent_workflow_id, started_at = _latest_run(dag.team_id, schedule_id)
    jobs = _jobs_by_saved_query(dag.team_id, parent_workflow_id)

    suspensions = {str(node.id): _suspension_detail(node) for node in nodes}
    blocked_seeds: set[str] = set()
    for node in nodes:
        node_id = str(node.id)
        job = jobs.get(str(node.saved_query_id)) if node.saved_query_id else None
        if suspensions[node_id] or (job is not None and job.status == DataModelingJobStatus.FAILED):
            blocked_seeds.add(node_id)

    # execute_dag skips a node whose ancestor failed or is suspended, so attribute those before
    # calling anything unexplained
    blocked_by: dict[str, str] = {}
    for seed in blocked_seeds:
        for descendant in downstream.get(seed, ()):
            blocked_by.setdefault(descendant, seed)

    names = {str(node.id): node.name for node in nodes}
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
    )


def _node_run(node: Node, *, job: DataModelingJob | None, suspension: str, blocked_by: str) -> NodeRun:
    saved_query_id = str(node.saved_query_id) if node.saved_query_id else None
    common = {
        "node_id": str(node.id),
        "name": node.name,
        "node_type": node.type,
        "saved_query_id": saved_query_id,
    }

    if node.type not in MATERIALIZING_TYPES:
        detail = (
            "view node — a run marks it successful and materializes nothing"
            if node.type == NodeType.VIEW.value
            else "source node — nothing to materialize"
        )
        return NodeRun(**common, status=NOT_MATERIALIZING, detail=detail)

    if job is not None:
        failed = job.status == DataModelingJobStatus.FAILED
        return NodeRun(
            **common,
            status=FAILED if failed else OK,
            detail=_first_line(job.error) if failed else f"{job.rows_materialized or 0} rows",
            job_id=str(job.id),
            workflow_id=job.workflow_id,
            workflow_run_id=job.workflow_run_id,
        )

    if suspension:
        return NodeRun(**common, status=SUSPENDED, detail=suspension)
    if blocked_by:
        return NodeRun(**common, status=BLOCKED, detail=f"upstream {blocked_by} failed or is suspended")
    return NodeRun(**common, status=MISSING, detail="declared on this tier but the run produced no job")


def _latest_run(team_id: int, schedule_id: str) -> tuple[str | None, datetime | None]:
    latest = (
        DataModelingJob.objects.filter(team_id=team_id, parent_workflow_id__startswith=f"execute-dag-{schedule_id}-")
        .order_by("-created_at")
        .values("parent_workflow_id", "created_at")
        .first()
    )
    if latest is None:
        return None, None
    return latest["parent_workflow_id"], latest["created_at"]


def _jobs_by_saved_query(team_id: int, parent_workflow_id: str | None) -> dict[str, DataModelingJob]:
    if parent_workflow_id is None:
        return {}
    # ascending, so the newest row wins when a node has both a serving and a shadow-engine job
    return {
        str(job.saved_query_id): job
        for job in DataModelingJob.objects.filter(team_id=team_id, parent_workflow_id=parent_workflow_id).order_by(
            "created_at"
        )
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
    suspended = ((node.properties or {}).get("system") or {}).get("suspended") or {}
    return "; ".join(
        f"{engine}: {(entry or {}).get('reason', 'unknown')}" for engine, entry in sorted(suspended.items())
    )


def _first_line(error: str | None) -> str:
    return (error or "").strip().splitlines()[0] if error else ""
