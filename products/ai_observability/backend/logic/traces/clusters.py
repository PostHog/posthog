import re
import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from typing import Self

from posthog.dataclasses import frozen
from posthog.temporal.ai_observability.trace_clustering.constants import NOISE_CLUSTER_ID

from .cluster_queries import ClusterRunRow
from .trace_queries import read_text

# Run ids read {team_id}_{level}_{YYYYMMDD}_{HHMMSS}[_{job_id}][_{run_label}], and only a manual admin run sets a label.
_UNLABELLED_RUN_ID = re.compile(r"\d+_[a-z]+_\d{8}_\d{6}(?:_(?P<job_id>[^_]+))?")


@frozen
class TraceCluster:
    run_id: str
    run_at: datetime
    job_id: str | None
    job_name: str | None
    cluster_id: int
    title: str | None
    description: str | None

    @property
    def is_outlier(self) -> bool:
        return self.cluster_id == NOISE_CLUSTER_ID


def _parsed_clusters(raw: str | None) -> list[object]:
    if raw is None:
        return []
    try:
        clusters = json.loads(raw)
    except ValueError:
        return []
    return clusters if isinstance(clusters, list) else []


def _is_manual(run: ClusterRunRow) -> bool:
    match = _UNLABELLED_RUN_ID.fullmatch(read_text(run.run_id) or "")
    return match is None or match["job_id"] != read_text(run.job_id)


def _memberships(trace_id: str, run: ClusterRunRow) -> Iterator[TraceCluster]:
    run_id = read_text(run.run_id)
    if run_id is None:
        return
    for cluster in _parsed_clusters(run.clusters):
        if not isinstance(cluster, Mapping):
            continue
        cluster_id = cluster.get("cluster_id")
        traces = cluster.get("traces")
        if isinstance(cluster_id, bool) or not isinstance(cluster_id, int) or not isinstance(traces, Mapping):
            continue
        if trace_id in traces:
            yield TraceCluster(
                run_id=run_id,
                run_at=run.timestamp,
                job_id=read_text(run.job_id),
                job_name=read_text(run.job_name),
                cluster_id=cluster_id,
                title=read_text(cluster.get("title")),
                description=read_text(cluster.get("description")),
            )


@frozen
class ClusterMemberships:
    clusters: tuple[TraceCluster, ...]

    @classmethod
    def of(cls, trace_id: str, runs: Sequence[ClusterRunRow]) -> Self:
        # Scheduled jobs rerun daily over overlapping windows, so each job keeps only its newest run that lists the trace.
        # A manual run can reuse a job's id with its own parameters, so it must not displace the job's scheduled run.
        newest_by_job: dict[str, TraceCluster] = {}
        for run in runs:
            if _is_manual(run):
                continue
            for membership in _memberships(trace_id, run):
                job = membership.job_id or ""
                current = newest_by_job.get(job)
                if current is None or membership.run_at > current.run_at:
                    newest_by_job[job] = membership
        return cls(
            clusters=tuple(
                sorted(newest_by_job.values(), key=lambda c: (c.is_outlier, -c.run_at.timestamp(), c.run_id))
            )
        )
