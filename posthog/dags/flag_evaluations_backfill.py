import time
from collections.abc import Callable, Iterator, Sequence
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
# and it keeps copied rows out of the consumer-lag query below. _partition and _offset are left out
# so that both are 0 on a copied row. _COPIED_ROW_FILTER relies on that.
_COPIED_COLUMNS = "uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id, _timestamp"

# A row from Kafka also has inserted_at = timestamp when its timestamp has no sub-second part and
# falls in the second that Kafka received it. Kafka gives offset 0 only to the first message in a
# partition, so the only Kafka row this filter can match is the first message in partition 0.
_COPIED_ROW_FILTER = "_partition = 0 AND _offset = 0 AND inserted_at = timestamp"

# A copied row's inserted_at is its timestamp, so the inserted_at != timestamp filter limits this
# query to rows that arrived through the Kafka path.
# Rows from every Kafka partition reach every shard. The slowest partition therefore sets the
# consumer's position. The lookback spans several days so that a partition that stops delivering
# stays in the query and reports its real lag. A partition that has delivered nothing for the whole
# lookback drops out of this query.
# Lag comes from _timestamp, the Kafka message time. A consumer that works through a backlog writes
# rows now, so the time a row is written does not show how far the consumer is behind.
# The lookback filters on inserted_at because only inserted_at has a skip index.
_KAFKA_LOOKBACK_DAYS = 7
_KAFKA_POSITION_QUERY = f"""
SELECT count(), max(lag_seconds)
FROM (
    SELECT _partition, dateDiff('second', max(_timestamp), now()) AS lag_seconds
    FROM {FLAG_EVALUATIONS_DATA_TABLE}
    WHERE inserted_at >= now() - INTERVAL {_KAFKA_LOOKBACK_DAYS} DAY AND inserted_at != timestamp
    GROUP BY _partition
)
"""

# Ingestion's producer sets each message's Kafka create time when it calls produce.
# librdkafka retries a failed produce until message.timeout.ms, which defaults to five minutes.
# A retried row keeps the create time of its first attempt, so it can reach flag_evaluations after rows
# with a later create time.
_KAFKA_DELIVERY_TIMEOUT = timedelta(minutes=5)

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


# The TTL expires each row at the start of toDate(timestamp) + FLAG_EVALUATIONS_TTL_DAYS.
# The day FLAG_EVALUATIONS_TTL_DAYS back has already expired when today starts.
# A TTL merge can drop the rows copied for that day soon after the insert.
_EARLIEST_START_DAYS_AGO = FLAG_EVALUATIONS_TTL_DAYS - 1


class FlagEvaluationsBackfillConfig(dagster.Config):
    start_date: str | None = pydantic.Field(
        default=None,
        description=(
            f"First day to copy (YYYY-MM-DD, UTC, inclusive). Defaults to {_EARLIEST_START_DAYS_AGO} days "
            "before today, which is also the earliest allowed value. A run copies the oldest days last. It "
            "stops at the first day that the TTL has expired by the time the run reaches it."
        ),
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description=(
            "Day after the last day to copy (YYYY-MM-DD, UTC, exclusive). Defaults to yesterday, which is also "
            "the latest allowed value. Every copied day therefore ended at least a day before the run. That gives "
            "late Kafka rows a day to reach flag_evaluations, so the job does not copy their calls a second time."
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
    disk_check_max_wait_seconds: int = pydantic.Field(
        default=2 * 60 * 60,
        description=(
            "Wait before each day while a replica has less free space than its move_factor reserve, which ClickHouse "
            "restores by moving parts to the next volume. Stop the shard when one such wait lasts this long. The "
            "limit starts again after each wait for a squash, deletes or data deletion run."
        ),
    )
    disk_check_poll_frequency_seconds: int = pydantic.Field(
        default=60,
        ge=1,
        description="How often to read the disks again while a replica is below its move_factor reserve.",
    )


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


@frozen
class ShardBackfillTotals:
    days: int
    rows: int


def earliest_backfill_day(today: date) -> date:
    return today - timedelta(days=_EARLIEST_START_DAYS_AGO)


def resolve_backfill_days(config: FlagEvaluationsBackfillConfig, *, today: date) -> tuple[date, ...]:
    latest_end = today - timedelta(days=1)
    earliest_start = earliest_backfill_day(today)
    start = date.fromisoformat(config.start_date) if config.start_date else earliest_start
    end = date.fromisoformat(config.end_date) if config.end_date else latest_end
    if start < earliest_start:
        raise dagster.Failure(
            description=f"start_date {start} is before {earliest_start}. "
            f"The {FLAG_EVALUATIONS_TTL_DAYS}-day TTL has already expired those rows."
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
    # Ingestion queues a call's fork row before its events row, so the fork row's Kafka create time is never
    # later than the events row's _timestamp. A source row whose _timestamp is at or after created_before can
    # still have its fork row in Kafka. Copying it would store the call twice, so the job skips it. Kafka then
    # delivers its fork row, or a later run copies it.
    select = f"""
SELECT {"count()" if dry_run else _COPIED_COLUMNS}
FROM {EVENTS_DATA_TABLE()}
PREWHERE event = %(event)s
    AND timestamp >= %(day_start)s AND timestamp < %(day_end)s{team_filter}
    AND (team_id, uuid) NOT IN (
        SELECT team_id, uuid FROM {FLAG_EVALUATIONS_DATA_TABLE}
        WHERE timestamp >= %(day_start)s AND timestamp < %(day_end)s{team_filter}
    )
WHERE _timestamp < %(created_before)s
    AND JSONType(properties, '$feature_flag') = 'String'
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
    days = resolve_backfill_days(config, today=datetime.now(UTC).date())
    context.log.info(f"Backfilling {len(days)} day(s), newest first, from {days[0]} back to {days[-1]}")
    return BackfillPlan(days=days, config=config)


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_backfill_shards(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: BackfillPlan,
) -> Iterator[dagster.DynamicOutput[int]]:
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
    because a run spans days. The weekly squash can start partway through, and the TTL can
    expire a planned day before the run reaches it. Days run newest first, so the run stops at
    the first expired day.
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

    def run(self, days: Sequence[date]) -> ShardBackfillTotals:
        if not self.config.dry_run:
            self.check_no_other_backfill_run()
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
        copied_days = 0
        for day in days:
            uncopied_days = len(days) - copied_days
            if self._reached_expired_day(day, uncopied_days=uncopied_days):
                break
            self.wait_for_parts_to_merge(day)
            blocking_run_check = self._wait_for_disk_and_blocking_runs()
            created_before = self.consumer_cutoff()
            # The waits above have no shared deadline. The TTL boundary moves at UTC midnight.
            if self._reached_expired_day(day, uncopied_days=uncopied_days):
                break
            try:
                rows = self.copy_day(day, copy_query, settings, created_before)
            finally:
                if not self.config.dry_run:
                    self.check_no_blocking_run_started(blocking_run_check, day=day)
            total_rows += rows
            copied_days += 1
            action = "would copy" if self.config.dry_run else "copied"
            self.log.info(f"Shard {self.shard_num}, {day}: {action} {rows} row(s)")
        return ShardBackfillTotals(days=copied_days, rows=total_rows)

    def _wait_for_disk_and_blocking_runs(self) -> BlockingRunCheck:
        # The post-copy check counts every blocking run that starts after wait_for_blocking_runs returns.
        # That wait therefore comes last. A squash can keep it waiting for hours. The disk can fill in that time.
        while True:
            self.wait_for_disk_headroom()
            blocking_run_check = self.wait_for_blocking_runs()
            if not self._hosts_moving_parts():
                return blocking_run_check

    def _reached_expired_day(self, day: date, *, uncopied_days: int) -> bool:
        if day >= earliest_backfill_day(datetime.now(UTC).date()):
            return False
        self.log.warning(
            f"Shard {self.shard_num}: stopping at {day}, because the TTL has already expired it. "
            f"{uncopied_days} planned day(s) are not copied."
        )
        return True

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

    def check_no_other_backfill_run(self) -> None:
        # Each shard op checks, because a shard re-executed from the UI skips the plan op. The check
        # fails rather than waits, because two waiting runs would wait on each other.
        others = describe_runs(
            self.instance,
            (flag_evaluations_backfill_job.name,),
            statuses=EXECUTING_RUN_STATUSES,
            exclude_run_id=self.run_id,
        )
        if others:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: {'; '.join(others)} is executing. "
                "Two backfills that copy the same day at once both insert its rows. "
                "Wait for that run to finish, then run the backfill again."
            )

    def wait_for_blocking_runs(self) -> BlockingRunCheck:
        while True:
            # The watermark comes before the scan. A run created during the scan then counts as created
            # after it. Run storage can record a creation time to the whole second. The watermark
            # therefore reaches one second back, and the post-copy check ignores runs that finished then.
            since = datetime.now(UTC) - timedelta(seconds=1)
            blockers = describe_runs(self.instance, BLOCKING_JOB_NAMES, exclude_run_id=self.run_id)
            if not blockers:
                break
            self.log.info(
                f"Waiting {self.config.blocking_run_poll_seconds}s for these runs to finish: {'; '.join(blockers)}"
            )
            time.sleep(self.config.blocking_run_poll_seconds)
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
            # A rerun for the same teams does not copy back the rows that earlier runs copied for other teams.
            team_filter = (
                f" AND team_id IN ({', '.join(map(str, self.config.team_ids))})" if self.config.team_ids else ""
            )
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: {'; '.join(started)} started while {day} copied. "
                "The copy can hold rows or person_ids that the run removed from sharded_flag_evaluations. "
                f"After that run finishes, delete the rows this job copied for {day} on shard {self.shard_num} "
                f"(`DELETE FROM {FLAG_EVALUATIONS_DATA_TABLE} WHERE toDate(timestamp) = '{day}' "
                f"AND {_COPIED_ROW_FILTER}{team_filter}`), then run the backfill again for the same teams."
            )

    def wait_for_disk_headroom(self) -> None:
        deadline = time.monotonic() + self.config.disk_check_max_wait_seconds
        while True:
            hosts_moving_parts = self._hosts_moving_parts()
            if not hosts_moving_parts:
                return
            hosts = ", ".join(hosts_moving_parts)
            if time.monotonic() >= deadline:
                raise dagster.Failure(
                    description=f"Stopping shard {self.shard_num}: ClickHouse is still moving parts off a disk "
                    f"below its move_factor reserve on {hosts} after {self.config.disk_check_max_wait_seconds}s."
                )
            self.log.info(f"Waiting for ClickHouse to move parts off a disk below its move_factor reserve on {hosts}")
            time.sleep(self.config.disk_check_poll_frequency_seconds)

    def _hosts_moving_parts(self) -> list[str]:
        """Return the replicas below their move_factor reserve.

        Raise when a replica is under the min_free_bytes floor or reports no disks.
        """
        # Every replica of the shard, including offline ones, stores a copy of each inserted part.
        disks_by_host = self.cluster.map_hosts_in_shard_by_role(
            self.shard_num, self._tagged(_read_policy_disks), node_role=self.node_role
        ).result()
        if not disks_by_host:
            raise dagster.Failure(description=f"No replica of shard {self.shard_num} reported its disks.")
        problems = []
        hosts_moving_parts = []
        for host, disks in disks_by_host.items():
            if not disks:
                problems.append(f"{host.connection_info.host} has no disks for {FLAG_EVALUATIONS_DATA_TABLE}")
                continue
            headroom = disk_headroom(disks)
            if headroom.usable_bytes < self.config.min_free_bytes:
                problems.append(
                    f"{host.connection_info.host} has {headroom.usable_bytes} usable bytes, "
                    f"under the floor of {self.config.min_free_bytes}"
                )
            elif headroom.below_move_line:
                hosts_moving_parts.append(host.connection_info.host)
        if problems:
            raise dagster.Failure(description=f"Stopping shard {self.shard_num}: " + "; ".join(problems))
        return hosts_moving_parts

    def consumer_cutoff(self) -> datetime:
        """Stop the shard when the Kafka path to flag_evaluations is too far behind.

        Otherwise return a cutoff such that flag_evaluations holds every fork row whose Kafka create time is
        before it.
        """
        checked_at = datetime.now(UTC)
        kafka_partitions, lag_seconds = self._on_copy_host(partial(self._first_row, _KAFKA_POSITION_QUERY))
        if kafka_partitions == 0:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: no row reached {FLAG_EVALUATIONS_DATA_TABLE} "
                f"through Kafka in the last {_KAFKA_LOOKBACK_DAYS} days, so the consumer position is unknown."
            )
        if lag_seconds > self.config.max_consumer_lag_seconds:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: the slowest Kafka partition is {lag_seconds}s behind, "
                f"over the limit of {self.config.max_consumer_lag_seconds}s. Copying now would insert rows "
                "that Kafka then delivers a second time."
            )
        # A part can reach the copy host after newer parts, through a postponed replication fetch or a queued
        # Distributed send. The anti-join reads only local parts. The cutoff therefore subtracts the whole lag
        # limit rather than the measured lag, which leaves that much slack for a late part.
        return checked_at - timedelta(seconds=self.config.max_consumer_lag_seconds) - _KAFKA_DELIVERY_TIMEOUT

    def copy_day(self, day: date, copy_query: str, settings: dict[str, Any], created_before: datetime) -> int:
        day_args = {
            "event": FLAG_EVALUATIONS_SOURCE_EVENT,
            "day_start": f"{day:%Y-%m-%d} 00:00:00",
            "day_end": f"{day + timedelta(days=1):%Y-%m-%d} 00:00:00",
            "created_before": f"{created_before:%Y-%m-%d %H:%M:%S}",
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
    totals = ShardBackfill(
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
            "days": dagster.MetadataValue.int(totals.days),
            "rows": dagster.MetadataValue.int(totals.rows),
            "dry_run": dagster.MetadataValue.bool(plan.config.dry_run),
        }
    )
    return totals.rows


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_backfill_job() -> None:
    """Copy $feature_flag_called history from events into flag_evaluations, one op per shard.

    Safe to re-run over the same window: the anti-join inserts only rows that are missing.
    """
    plan = plan_flag_evaluations_backfill()
    shards = get_backfill_shards(plan=plan)
    shards.map(lambda shard_num: backfill_flag_evaluations_shard(shard_num, plan))
