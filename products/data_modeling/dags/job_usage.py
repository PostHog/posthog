from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

import dagster

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.workload import Workload
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.resources import OpsClickhouseClusterResource
from posthog.dataclasses import frozen

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)

USAGE_FIELDS = ["read_bytes", "read_rows", "cpu_microseconds", "query_count", "usage_updated_at"]
BATCH_SIZE = 500

# FINAL folds archive fragments for the same query before counting it. The v3 archive
# already rolls leaf CPU and reads into the root, so summing leaf rows again doubles cost.
USAGE_SQL = """
SELECT team_id, lc_temporal__workflow_id, lc_temporal__workflow_run_id,
       sum(read_bytes), sum(read_rows), sum(ProfileEvents_OSCPUVirtualTimeMicroseconds), count()
FROM query_log_archive FINAL
WHERE initial_query_start_time >= %(start)s AND initial_query_start_time < %(end)s
  AND is_initial_query
  AND type IN ('QueryFinish', 'ExceptionWhileProcessing', 'ExceptionBeforeStart')
  AND lc_feature = 'data_modeling'
  AND (team_id, lc_temporal__workflow_id, lc_temporal__workflow_run_id) IN (SELECT team_id, workflow_id, workflow_run_id FROM model_usage_jobs)
GROUP BY team_id, lc_temporal__workflow_id, lc_temporal__workflow_run_id
"""


@frozen
class CollectedJobUsage:
    measured_jobs: int = 0
    ambiguous_jobs: int = 0
    expired_jobs: int = 0


class JobUsageCollector:
    @staticmethod
    def collect_jobs(
        cluster: ClickhouseCluster, jobs: list[DataModelingJob], end: datetime, query_settings: dict[str, str | int]
    ) -> CollectedJobUsage:
        # Check beyond the day's jobs because retries and other engines can share a run ID.
        counts: Counter[tuple[int | None, str | None, str | None]] = Counter()
        for offset in range(0, len(jobs), BATCH_SIZE):
            keys = {(job.team_id, job.workflow_id, job.workflow_run_id) for job in jobs[offset : offset + BATCH_SIZE]}
            counts.update(
                key
                for key in DataModelingJob.objects.filter(
                    team_id__in={key[0] for key in keys},
                    workflow_id__in={key[1] for key in keys},
                    workflow_run_id__in={key[2] for key in keys},
                ).values_list("team_id", "workflow_id", "workflow_run_id")
                if key in keys
            )
        unique = {key: job for job in jobs if counts[key := (job.team_id, job.workflow_id, job.workflow_run_id)] == 1}
        ambiguous = len(jobs) - len(unique)
        # The source has finite retention. A partial lifetime must remain unknown.
        cutoff = datetime.now(UTC) - timedelta(days=14)
        expired = sum(job.created_at < cutoff for job in unique.values())
        unique = {key: job for key, job in unique.items() if job.created_at >= cutoff}
        if not unique:
            return CollectedJobUsage(ambiguous_jobs=ambiguous, expired_jobs=expired)
        start = min(job.created_at for job in unique.values())
        rows = cluster.any_host_by_role(
            lambda client: client.execute(
                USAGE_SQL,
                {"start": start, "end": end},
                settings=query_settings,
                external_tables=[
                    {
                        "name": "model_usage_jobs",
                        "structure": [("team_id", "Int64"), ("workflow_id", "String"), ("workflow_run_id", "String")],
                        "data": list(unique),
                    }
                ],
            ),
            NodeRole.OPS,
            # OPS replicas can be marked online; the role selects the archive hosts.
            workload=Workload.DEFAULT,
        ).result()
        updated: list[DataModelingJob] = []
        for team_id, workflow_id, workflow_run_id, read_bytes, read_rows, cpu, query_count in rows:
            job = unique[(team_id, workflow_id, workflow_run_id)]
            job.read_bytes, job.read_rows, job.cpu_microseconds, job.query_count = (
                read_bytes,
                read_rows,
                cpu,
                query_count,
            )
            job.usage_updated_at = datetime.now(UTC)
            updated.append(job)
        DataModelingJob.objects.bulk_update(updated, USAGE_FIELDS, batch_size=BATCH_SIZE)
        return CollectedJobUsage(measured_jobs=len(updated), ambiguous_jobs=ambiguous, expired_jobs=expired)

    @staticmethod
    def collect(cluster: ClickhouseCluster, day: date, query_settings: dict[str, str | int]) -> dict[str, int]:
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)
        if end > datetime.now(UTC):
            raise ValueError("Usage can only be collected for complete UTC days.")
        jobs = list(
            DataModelingJob.objects.filter(
                engine=DataModelingJobEngine.CLICKHOUSE,
                status__in=[
                    DataModelingJobStatus.COMPLETED,
                    DataModelingJobStatus.FAILED,
                    DataModelingJobStatus.CANCELLED,
                ],
                last_run_at__gte=end - timedelta(days=1),
                last_run_at__lt=end,
                team_id__isnull=False,
                workflow_id__isnull=False,
                workflow_run_id__isnull=False,
            )
            .exclude(workflow_id="")
            .exclude(workflow_run_id="")
            .only(
                "id",
                "team_id",
                "workflow_id",
                "workflow_run_id",
                "created_at",
            )
        )
        if not jobs:
            return {"measured_jobs": 0, "ambiguous_jobs": 0, "expired_jobs": 0}
        result = JobUsageCollector.collect_jobs(cluster, jobs, end, query_settings)
        return {
            "measured_jobs": result.measured_jobs,
            "ambiguous_jobs": result.ambiguous_jobs,
            "expired_jobs": result.expired_jobs,
        }


@dagster.op
def collect_model_job_usage(
    context: dagster.OpExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> None:
    result = JobUsageCollector.collect(
        cluster,
        date.fromisoformat(context.partition_key),
        {**settings_with_log_comment(context), "max_threads": 4, "max_bytes_before_external_group_by": 512 * 1024**2},
    )
    context.add_output_metadata(result)
    if result["ambiguous_jobs"]:
        context.log.warning(f"Left {result['ambiguous_jobs']} jobs unmeasured because their workflow run is ambiguous.")


@dagster.job(
    partitions_def=dagster.DailyPartitionsDefinition(start_date="2026-10-16", timezone="UTC"),
    resource_defs={"cluster": OpsClickhouseClusterResource(max_execution_time=600, max_memory_usage=2 * 1024**3)},
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value, "dagster/max_runtime": 1800},
)
def model_job_usage_job() -> None:
    collect_model_job_usage()


model_job_usage_schedule = dagster.build_schedule_from_partitioned_job(
    model_job_usage_job,
    hour_of_day=3,
    minute_of_hour=0,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
