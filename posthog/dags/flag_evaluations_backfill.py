import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, TypeVar

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags, Feature, tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common import EXECUTING_RUN_STATUSES, JobOwners, dagster_tags, describe_runs
from posthog.dags.data_deletion_requests import DELETION_JOB_NAMES
from posthog.dags.deletes import deletes_job
from posthog.dags.person_overrides import squash_person_overrides
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_SOURCE_EVENT,
    FLAG_EVALUATIONS_TTL_DAYS,
)
from posthog.models.raw_sessions.sessions_v3 import GET_NUM_RAW_SESSIONS_ACTIVE_PARTS

T = TypeVar("T")

OWNER_TAG = {"owner": JobOwners.TEAM_FEATURE_FLAGS.value}

GIB = 1024**3
TIB = 1024 * GIB

# These jobs rewrite or delete rows in sharded_events and sharded_flag_evaluations, directly or
# through deletes_job. A day copied while one of them runs can read a row before the job changes
# it and insert it after the job swept sharded_flag_evaluations, so the copy keeps what the job
# removed: a stale person_id after a squash, or a row or property that a deletion erased.
BLOCKING_JOB_NAMES = (squash_person_overrides.name, deletes_job.name, *DELETION_JOB_NAMES)

_FINISHED_RUN_STATUSES = (
    dagster.DagsterRunStatus.SUCCESS,
    dagster.DagsterRunStatus.FAILURE,
    dagster.DagsterRunStatus.CANCELED,
)

# The nine DEFAULT columns are left out so the shard computes them from properties, the same way
# it does for rows from Kafka. inserted_at is left out so its DEFAULT stamps the event timestamp:
# that keeps every copied row inside the deletion sweep's `inserted_at <= request.created_at` bound,
# and it keeps copied rows out of the consumer-lag query below.
_COPIED_COLUMNS = "uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id, _timestamp"

# A copied row's inserted_at is its timestamp, and the window ends no later than the start of
# yesterday, so every row this query reads arrived through the Kafka path.
_KAFKA_POSITION_QUERY = f"""
SELECT count(), dateDiff('second', max(inserted_at), now64(6))
FROM {FLAG_EVALUATIONS_DATA_TABLE}
WHERE inserted_at >= now() - INTERVAL 1 DAY
"""

_STORAGE_POLICY_DISKS_QUERY = f"""
SELECT policy.volume_priority, policy.move_factor, disk.free_space, disk.total_space
FROM system.storage_policies AS policy
ARRAY JOIN policy.disks AS disk_name
INNER JOIN system.disks AS disk ON disk.name = disk_name
WHERE policy.policy_name = (
    SELECT storage_policy FROM system.tables
    WHERE database = currentDatabase() AND name = '{FLAG_EVALUATIONS_DATA_TABLE}'
)
"""


class FlagEvaluationsBackfillConfig(dagster.Config):
    start_date: str | None = pydantic.Field(
        default=None,
        description="First day to copy (YYYY-MM-DD, UTC, inclusive). Defaults to 90 days before today.",
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description=(
            "Day after the last day to copy (YYYY-MM-DD, UTC, exclusive). Defaults to yesterday, which is also "
            "the latest allowed value: the Kafka path must have delivered every row before it."
        ),
    )
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Copy only these teams. Leave empty to copy every team."
    )
    team_id_chunks: int = pydantic.Field(
        default=1, ge=1, description="Split each day into this many inserts by team_id % team_id_chunks."
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Count the rows each day would copy instead of inserting them. The checks before each day still run.",
    )
    max_insert_threads: int = pydantic.Field(default=1, description="ClickHouse max_insert_threads for each insert.")
    max_execution_time_seconds: int = pydantic.Field(
        default=4 * 60 * 60, description="ClickHouse max_execution_time for each insert."
    )
    max_memory_usage_bytes: int = pydantic.Field(
        default=32 * GIB, description="ClickHouse max_memory_usage for each insert."
    )
    min_free_bytes: int = pydantic.Field(
        default=1 * TIB,
        description=(
            "Stop the shard when any of its replicas has less usable free space than this. Usable space leaves out "
            "the share of each disk that ClickHouse keeps free by moving parts to the next volume."
        ),
    )
    max_consumer_lag_seconds: int = pydantic.Field(
        default=60 * 60,
        description="Stop the shard when the Kafka path to flag_evaluations is further behind than this.",
    )
    blocking_run_poll_seconds: int = pydantic.Field(
        default=5 * 60,
        description="How often to check again while a squash, deletes or data deletion request run is active.",
    )
    max_unmerged_parts: int = pydantic.Field(
        default=100,
        description="Wait before each day until the day's partition has fewer active parts than this. 0 disables the wait.",
    )
    parts_check_poll_frequency_seconds: int = 30
    parts_check_max_wait_seconds: int = 60 * 60


@frozen
class BackfillPlan:
    # Newest first, so a run that stops partway leaves contiguous recent history.
    days: tuple[date, ...]
    config: FlagEvaluationsBackfillConfig


@frozen
class BlockingRunCheck:
    since: datetime
    finished_runs: frozenset[str]


@frozen
class PolicyDisk:
    volume_priority: int
    move_factor: float
    free_bytes: int
    total_bytes: int


@frozen
class DiskHeadroom:
    usable_bytes: int
    below_move_line: bool


def resolve_backfill_days(config: FlagEvaluationsBackfillConfig, *, today: date) -> tuple[date, ...]:
    latest_end = today - timedelta(days=1)
    start = (
        date.fromisoformat(config.start_date)
        if config.start_date
        else today - timedelta(days=FLAG_EVALUATIONS_TTL_DAYS)
    )
    end = date.fromisoformat(config.end_date) if config.end_date else latest_end
    earliest_start = today - timedelta(days=FLAG_EVALUATIONS_TTL_DAYS)
    if start < earliest_start:
        raise dagster.Failure(
            description=f"start_date {start} is before {earliest_start}. The TTL drops those rows as soon as they land."
        )
    if end > latest_end:
        raise dagster.Failure(description=f"end_date {end} is after yesterday ({latest_end}).")
    if start >= end:
        raise dagster.Failure(description=f"start_date {start} must be before end_date {end}.")
    return tuple(end - timedelta(days=offset) for offset in range(1, (end - start).days + 1))


def disk_headroom(disks: Sequence[PolicyDisk]) -> DiskHeadroom:
    """Return the free space an insert can use on one host, under the table's storage policy.

    New parts land on the first volume. When a disk's free space drops below move_factor of its
    size, ClickHouse moves parts from it to the next volume, so that share of the disk is not
    usable. The last volume has no next volume, so all of its free space is usable.
    """
    last_volume = max(disk.volume_priority for disk in disks)
    usable = 0.0
    below_move_line = False
    for disk in disks:
        reserve = disk.move_factor * disk.total_bytes if disk.volume_priority < last_volume else 0.0
        usable += disk.free_bytes - reserve
        below_move_line = below_move_line or disk.free_bytes < reserve
    return DiskHeadroom(usable_bytes=int(usable), below_move_line=below_move_line)


def build_copy_query(*, dry_run: bool, filter_team_ids: bool, chunked: bool) -> str:
    team_filter = ""
    if filter_team_ids:
        team_filter += " AND team_id IN %(team_ids)s"
    if chunked:
        team_filter += " AND modulo(team_id, %(team_id_chunks)s) = %(chunk)s"
    # The eligibility filter is the ingestion fork's rule, in the form PARITY_CHECK.md uses.
    select = f"""
SELECT {"count()" if dry_run else _COPIED_COLUMNS}
FROM {EVENTS_DATA_TABLE()}
PREWHERE event = %(event)s
    AND timestamp >= %(day_start)s AND timestamp < %(day_end)s{team_filter}
    AND uuid NOT IN (
        SELECT uuid FROM {FLAG_EVALUATIONS_DATA_TABLE}
        WHERE timestamp >= %(day_start)s AND timestamp < %(day_end)s{team_filter}
    )
WHERE JSONType(properties, '$feature_flag') = 'String'
    AND JSONExtractString(properties, '$feature_flag') != ''
"""
    if dry_run:
        return select
    return f"INSERT INTO {FLAG_EVALUATIONS_DATA_TABLE} ({_COPIED_COLUMNS}){select}"


@dagster.op(tags=OWNER_TAG)
def plan_flag_evaluations_backfill(
    context: dagster.OpExecutionContext, config: FlagEvaluationsBackfillConfig
) -> BackfillPlan:
    """Resolve the window once, so a shard re-executed from the UI later copies the same days."""
    if not config.dry_run:
        # Two runs that copy the same day at once both find the day's rows missing from the anti-join.
        # Both runs then insert those rows.
        other_runs = describe_runs(
            context.instance, (context.job_name,), statuses=EXECUTING_RUN_STATUSES, exclude_run_id=context.run_id
        )
        if other_runs:
            raise dagster.Failure(description="Another backfill is running: " + "; ".join(other_runs))
    days = resolve_backfill_days(config, today=datetime.now(UTC).date())
    context.log.info(f"Backfilling {len(days)} day(s), newest first, from {days[0]} back to {days[-1]}")
    return BackfillPlan(days=days, config=config)


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_backfill_shards(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: BackfillPlan,
):
    """Fan out one backfill op per shard.

    Takes the plan as input so the fan-out runs after it. The mapping key makes each shard
    re-executable on its own from the Dagster UI.
    """
    shards = sorted(cluster.shards)
    context.log.info(f"Fanning out the backfill of {len(plan.days)} day(s) to {len(shards)} shard op(s)")
    for shard_num in shards:
        yield dagster.DynamicOutput(shard_num, mapping_key=f"shard_{shard_num}")


@frozen
class ShardBackfill:
    """Copy planned days of $feature_flag_called events on one shard into flag_evaluations.

    sharded_events and sharded_flag_evaluations share a shard key, so the copy reads and writes
    only this shard's local tables. The checks run before every day, not once at the start,
    because a run spans days and the weekly squash can start partway through.
    """

    cluster: ClickhouseCluster
    shard_num: int
    config: FlagEvaluationsBackfillConfig
    instance: dagster.DagsterInstance
    run_id: str
    log: dagster.DagsterLogManager
    query_tags: DagsterTags
    workload: Workload
    node_role: NodeRole

    def run(self, days: Sequence[date]) -> int:
        copy_query = build_copy_query(
            dry_run=self.config.dry_run,
            filter_team_ids=bool(self.config.team_ids),
            chunked=self.config.team_id_chunks > 1,
        )
        settings: dict[str, Any] = {
            "max_execution_time": self.config.max_execution_time_seconds,
            "max_memory_usage": self.config.max_memory_usage_bytes,
            "max_insert_threads": self.config.max_insert_threads,
        }
        total_rows = 0
        for day in days:
            self.wait_for_parts_to_merge(day)
            blocking_run_check = self.wait_for_blocking_runs()
            self.check_disk_headroom()
            self.check_consumer_lag()
            try:
                rows = self.copy_day(day, copy_query, settings)
            finally:
                if not self.config.dry_run:
                    self.check_no_blocking_run_started(blocking_run_check, day=day)
            total_rows += rows
            action = "would copy" if self.config.dry_run else "copied"
            self.log.info(f"Shard {self.shard_num}, {day}: {action} {rows} row(s)")
        return total_rows

    def wait_for_parts_to_merge(self, day: date) -> None:
        if self.config.max_unmerged_parts <= 0:
            return
        query = GET_NUM_RAW_SESSIONS_ACTIVE_PARTS([f"{day:%Y%m}"], table=FLAG_EVALUATIONS_DATA_TABLE, use_cluster=False)
        deadline = time.monotonic() + self.config.parts_check_max_wait_seconds
        while True:
            active_parts = self._on_copy_host(partial(self._first_row, query))[0]
            if active_parts < self.config.max_unmerged_parts:
                return
            if time.monotonic() > deadline:
                raise dagster.Failure(
                    description=f"Stopping shard {self.shard_num}: partition {day:%Y%m} still has {active_parts} "
                    f"active parts after {self.config.parts_check_max_wait_seconds}s."
                )
            self.log.info(f"Waiting for partition {day:%Y%m} to merge: {active_parts} active parts")
            time.sleep(self.config.parts_check_poll_frequency_seconds)

    def wait_for_blocking_runs(self) -> BlockingRunCheck:
        while blockers := describe_runs(self.instance, BLOCKING_JOB_NAMES, exclude_run_id=self.run_id):
            self.log.info(
                f"Waiting {self.config.blocking_run_poll_seconds}s for these runs to finish: {'; '.join(blockers)}"
            )
            time.sleep(self.config.blocking_run_poll_seconds)
        # Run storage can record a creation time to the whole second, so the check reaches one second
        # back. The returned value lists the runs that finished inside that second. The check ignores them.
        since = datetime.now(UTC) - timedelta(seconds=1)
        finished = describe_runs(
            self.instance,
            BLOCKING_JOB_NAMES,
            statuses=_FINISHED_RUN_STATUSES,
            created_after=since,
            exclude_run_id=self.run_id,
        )
        return BlockingRunCheck(since=since, finished_runs=frozenset(finished))

    def check_no_blocking_run_started(self, check: BlockingRunCheck, *, day: date) -> None:
        started = [
            run
            for run in describe_runs(
                self.instance,
                BLOCKING_JOB_NAMES,
                statuses=(*EXECUTING_RUN_STATUSES, *_FINISHED_RUN_STATUSES),
                created_after=check.since,
                exclude_run_id=self.run_id,
            )
            if run not in check.finished_runs
        ]
        if started:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: {'; '.join(started)} started while {day} copied. "
                "The copy can hold rows or person_ids that the run removed from sharded_flag_evaluations. "
                f"After that run finishes, delete the rows this job copied for {day} on shard {self.shard_num} "
                f"(`DELETE FROM {FLAG_EVALUATIONS_DATA_TABLE} WHERE toDate(timestamp) = '{day}' "
                "AND inserted_at = timestamp`), then run the backfill again."
            )

    def check_disk_headroom(self) -> None:
        # Every replica of the shard, including offline ones, stores a copy of each inserted part.
        disks_by_host = self.cluster.map_hosts_in_shard_by_role(
            self.shard_num, self._tagged(_read_policy_disks), node_role=self.node_role
        ).result()
        if not disks_by_host:
            raise dagster.Failure(description=f"No replica of shard {self.shard_num} reported its disks.")
        problems = []
        for host, disks in disks_by_host.items():
            if not disks:
                problems.append(f"{host.connection_info.host} has no disks for {FLAG_EVALUATIONS_DATA_TABLE}")
                continue
            headroom = disk_headroom(disks)
            if headroom.below_move_line:
                problems.append(
                    f"{host.connection_info.host} has a disk with less free space than its move_factor reserve, "
                    "so ClickHouse is moving parts off it"
                )
            elif headroom.usable_bytes < self.config.min_free_bytes:
                problems.append(
                    f"{host.connection_info.host} has {headroom.usable_bytes} usable bytes, "
                    f"under the floor of {self.config.min_free_bytes}"
                )
        if problems:
            raise dagster.Failure(description=f"Stopping shard {self.shard_num}: " + "; ".join(problems))

    def check_consumer_lag(self) -> None:
        kafka_rows, lag_seconds = self._on_copy_host(partial(self._first_row, _KAFKA_POSITION_QUERY))
        if kafka_rows == 0:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: no row reached {FLAG_EVALUATIONS_DATA_TABLE} "
                "through Kafka in the last day, so the consumer position is unknown."
            )
        if lag_seconds > self.config.max_consumer_lag_seconds:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: the Kafka path is {lag_seconds}s behind, "
                f"over the limit of {self.config.max_consumer_lag_seconds}s. Copying now would insert rows "
                "that Kafka then delivers a second time."
            )

    def copy_day(self, day: date, copy_query: str, settings: dict[str, Any]) -> int:
        day_args = {
            "event": FLAG_EVALUATIONS_SOURCE_EVENT,
            "day_start": f"{day:%Y-%m-%d} 00:00:00",
            "day_end": f"{day + timedelta(days=1):%Y-%m-%d} 00:00:00",
            "team_ids": tuple(self.config.team_ids or ()),
            "team_id_chunks": self.config.team_id_chunks,
        }

        def run_chunk(chunk: int, client: Client) -> int:
            result = sync_execute(
                copy_query,
                {**day_args, "chunk": chunk},
                settings=settings,
                workload=self.workload,
                sync_client=client,
            )
            if self.config.dry_run:
                return result[0][0]
            # sync_execute returns the written row count for an INSERT that wrote rows. It returns
            # an empty result for an INSERT that wrote none.
            return result if isinstance(result, int) else 0

        return sum(self._on_copy_host(partial(run_chunk, chunk)) for chunk in range(self.config.team_id_chunks))

    def _first_row(self, query: str, client: Client) -> tuple:
        return sync_execute(query, workload=self.workload, sync_client=client)[0]

    def _tagged(self, fn: Callable[[Client], T]) -> Callable[[Client], T]:
        # The cluster runs fn on a pool thread. The query tags do not cross into that thread.
        def tagged(client: Client) -> T:
            with tags_context(
                kind="dagster", dagster=self.query_tags, product=ProductKey.FEATURE_FLAGS, feature=Feature.BACKFILL
            ):
                return fn(client)

        return tagged

    def _on_copy_host(self, fn: Callable[[Client], T]) -> T:
        result = self.cluster.map_any_host_in_shards_by_role(
            {self.shard_num: self._tagged(fn)}, workload=self.workload, node_role=self.node_role
        ).result()
        return next(iter(result.values()))


def _read_policy_disks(client: Client) -> list[PolicyDisk]:
    return [
        PolicyDisk(volume_priority=row[0], move_factor=row[1], free_bytes=row[2], total_bytes=row[3])
        for row in sync_execute(_STORAGE_POLICY_DISKS_QUERY, sync_client=client)
    ]


@dagster.op(tags=OWNER_TAG)
def backfill_flag_evaluations_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard_num: int,
    plan: BackfillPlan,
) -> int:
    workload, node_role = (Workload.OFFLINE, NodeRole.DATA) if is_cloud() else (Workload.DEFAULT, NodeRole.ALL)
    total_rows = ShardBackfill(
        cluster=cluster,
        shard_num=shard_num,
        config=plan.config,
        instance=context.instance,
        run_id=context.run_id,
        log=context.log,
        query_tags=dagster_tags(context),
        workload=workload,
        node_role=node_role,
    ).run(plan.days)
    context.add_output_metadata(
        {
            "shard": dagster.MetadataValue.int(shard_num),
            "days": dagster.MetadataValue.int(len(plan.days)),
            "rows": dagster.MetadataValue.int(total_rows),
            "dry_run": dagster.MetadataValue.bool(plan.config.dry_run),
        }
    )
    return total_rows


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_backfill_job():
    """Copy $feature_flag_called history from events into flag_evaluations, one op per shard.

    Safe to re-run over the same window: the anti-join inserts only rows that are missing.
    """
    plan = plan_flag_evaluations_backfill()
    shards = get_backfill_shards(plan=plan)
    shards.map(lambda shard_num: backfill_flag_evaluations_shard(shard_num, plan))
