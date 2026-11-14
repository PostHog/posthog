"""Write the rows a geoip_backfill_staging_job run staged into `sharded_events`, and delete their originals.

On each shard, the job inserts a team chunk's staged rows into a local table with the structure of
`sharded_events`, then attaches that table's partitions to `sharded_events` (`ATTACH PARTITION FROM`).
An attach fires no materialized view, so `events_recent`, the raw sessions tables and what reads them,
such as batch exports and the flag `last_called_at` sync, never see the events a second time. A copy
keeps its original's `inserted_at`, so a deletion requested before the resend still covers it.

A copy has the sort key of its original and a newer `_timestamp`. Until a merge collapses the two, a
query without FINAL counts the event twice, and parts at the maximum merge size are not merged again.
So after the last chunk the job deletes the originals with a lightweight delete. The delete names each
row by the `(team_id, uuid, _timestamp, person_id, properties)` that staging read, so it never removes
a copy, or an original that changed after staging.

A re-run is safe: a copy is written only while the newest row of its event is the original that staging
read, and the delete removes only originals.

`events_json` and `sharded_ai_events` read Kafka, not `sharded_events`, so this job does not repair them.
`sharded_ai_events` is a plain MergeTree, where only a mutation could replace a row. Its rows drop
after the team's AI events retention, 30 days by default.
"""

import re
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import (
    MUTATION_SETTINGS,
    ClickhouseCluster,
    HostInfo,
    LightweightDeleteMutationRunner,
    MutationWaiter,
    wait_for_mutations_on_shards,
)
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.dags.common import EXECUTING_RUN_STATUSES, dagster_tags, describe_runs
from posthog.dags.common.shards import shard_workload, tagged
from posthog.dags.flag_evaluations_backfill import BlockingRunCheck, blocking_runs_started_since, wait_for_blocking_runs
from posthog.dags.geoip_backfill import (
    OWNER_TAG,
    PRODUCT,
    STAGING_TABLE_PREFIX,
    EventColumn,
    GeoipStagingTable,
    staged_team_ids,
)
from posthog.dataclasses import frozen
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.raw_sessions.sessions_v3 import GET_NUM_RAW_SESSIONS_ACTIVE_PARTS

GIB = 1024**3


class GeoipResendConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run to resend.")
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Resend only these teams. Leave empty to resend every staged team."
    )
    dry_run: bool = pydantic.Field(
        default=True, description="Count the rows each team chunk would write, and write nothing."
    )
    team_chunk_size: int = pydantic.Field(default=50, ge=1, description="Teams per insert.")
    max_unmerged_parts: int = pydantic.Field(
        default=300,
        description="Wait before each insert until every partition it writes has fewer active parts. 0 disables the wait.",
    )
    parts_check_poll_seconds: int = 30
    parts_check_max_wait_seconds: int = 60 * 60
    blocking_run_poll_seconds: int = pydantic.Field(
        default=5 * 60,
        description="How often to check again while a squash, deletes or data deletion request run is active.",
    )
    max_execution_time_seconds: int = pydantic.Field(default=30 * 60, description="ClickHouse max_execution_time.")
    max_memory_usage_bytes: int = pydantic.Field(default=32 * GIB, description="ClickHouse max_memory_usage.")


@frozen
class ResendPlan:
    table: GeoipStagingTable
    team_ids: tuple[int, ...]
    config: GeoipResendConfig
    blocking_run_check: BlockingRunCheck | None


@frozen
class StagedBounds:
    timestamp_from: datetime
    timestamp_to: datetime
    rows: int

    def partitions(self) -> list[str]:
        partitions = []
        month = self.timestamp_from.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while month <= self.timestamp_to:
            partitions.append(f"{month:%Y%m}")
            month = (month + timedelta(days=32)).replace(day=1)
        return partitions

    def args(self, team_ids: tuple[int, ...]) -> dict[str, Any]:
        return {
            "team_ids": team_ids,
            "timestamp_from": f"{self.timestamp_from:%Y-%m-%d %H:%M:%S.%f}",
            "timestamp_to": f"{self.timestamp_to:%Y-%m-%d %H:%M:%S.%f}",
        }


@frozen
class ShardResendTotals:
    written: int
    changed_since_staging: int


def resend_query(table: GeoipStagingTable, columns: Sequence[EventColumn], *, into: str | None) -> str:
    """The staged rows of a team chunk whose event's newest row is still the original that staging read.

    A deletion, a person squash or a later version that changed the event after staging would be undone
    by the staged copy, so such a row stays out. Once a copy is in, it is the newest row, so a re-run
    writes nothing. `into` names the table to insert into; without it the query counts the rows.
    """
    staged_columns = ", ".join(f"s.{column.quoted}" for column in columns)
    select = f"""
        SELECT {staged_columns if into else "count()"}
        FROM {table.qualified_name} AS s FINAL
        INNER JOIN (
            SELECT
                team_id,
                uuid,
                max(_timestamp) AS newest_written_at,
                argMax(properties, _timestamp) AS newest_properties,
                argMax(person_id, _timestamp) AS newest_person_id
            FROM {EVENTS_DATA_TABLE()}
            WHERE team_id IN %(team_ids)s
                AND timestamp >= %(timestamp_from)s AND timestamp <= %(timestamp_to)s
                AND uuid IN (SELECT uuid FROM {table.qualified_name} WHERE team_id IN %(team_ids)s)
            GROUP BY team_id, uuid
        ) AS e ON s.team_id = e.team_id AND s.uuid = e.uuid
        WHERE s.team_id IN %(team_ids)s
            AND e.newest_written_at = s.original_written_at
            AND e.newest_properties = s.original_properties
            AND e.newest_person_id = s.person_id
    """
    if into is None:
        return select
    column_list = ", ".join(column.quoted for column in columns)
    return f"INSERT INTO {into} ({column_list}) {select}"


def delete_originals_predicate(table: GeoipStagingTable) -> str:
    """The originals of the staged rows, as staging read them. A copy or a changed original never matches."""
    return f"""team_id IN %(team_ids)s
        AND (team_id, uuid, _timestamp, person_id, cityHash64(properties)) IN (
            SELECT team_id, uuid, original_written_at, person_id, cityHash64(original_properties)
            FROM {table.qualified_name} FINAL
            WHERE team_id IN %(team_ids)s
        )"""


@frozen
class ResendAttachTable:
    """A local table on one host of a shard, which holds a chunk's copies until they are attached.

    It has the structure of `sharded_events` with the engine minus replication, which is what `ATTACH
    PARTITION FROM` needs. The name matches the "tmp_*" glob of the schema convergence gate.
    """

    run_id: uuid.UUID

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{STAGING_TABLE_PREFIX}resend_{self.run_id.hex}"

    def recreate(self, client: Client) -> None:
        # A table left by a failed run holds copies that are either attached already or written again
        # by this run, so dropping it loses nothing.
        self.drop(client)
        [[engine_full]] = client.execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": EVENTS_DATA_TABLE()},
        )
        engine = local_engine(engine_full)
        events = f"{settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()}"
        client.execute(f"CREATE TABLE {self.qualified_name} AS {events} ENGINE = {engine}")

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")


def local_engine(engine_full: str) -> str:
    """`engine_full` of a replicated table, with the engine's replication arguments removed."""
    engine = re.sub(
        r"^Replicated(\w+)\('[^']*',\s*'[^']*'(?:,\s*)?",
        lambda match: f"{match.group(1)}(",
        engine_full,
        count=1,
    )
    if engine.startswith("Replicated"):
        raise dagster.Failure(description=f"Cannot derive a local engine from {engine_full}")
    return engine


def _chunks(items: Sequence[int], size: int) -> Iterator[tuple[int, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


def check_no_other_resend_run(instance: dagster.DagsterInstance, run_id: str) -> None:
    # The check fails rather than waits, because two waiting runs would wait on each other.
    others = describe_runs(
        instance, (geoip_backfill_resend_job.name,), statuses=EXECUTING_RUN_STATUSES, exclude_run_id=run_id
    )
    if others:
        raise dagster.Failure(
            description=f"{'; '.join(others)} is executing. Two resends of the same events both attach "
            "their copies. Wait for that run to finish, then run the resend again."
        )


@dagster.op(tags=OWNER_TAG)
def plan_geoip_resend(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: GeoipResendConfig,
) -> ResendPlan:
    """Read the staged teams, then wait until no squash, deletes or data deletion request run is active."""
    table = GeoipStagingTable(id=uuid.UUID(config.staging_run_id))
    team_ids = staged_team_ids(cluster, table, config.team_ids)
    check = None
    if not config.dry_run:
        check_no_other_resend_run(context.instance, context.run_id)
        check = wait_for_blocking_runs(context.instance, context.run_id, context.log, config.blocking_run_poll_seconds)
    context.log.info(f"Resending {len(team_ids)} team(s) from {table.qualified_name}")
    return ResendPlan(table=table, team_ids=team_ids, config=config, blocking_run_check=check)


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_resend_shards(
    cluster: dagster.ResourceParam[ClickhouseCluster], plan: ResendPlan
) -> Iterator[dagster.DynamicOutput[int]]:
    """Fan out one op per shard, so a failed shard can be re-executed on its own from the UI."""
    for shard_num in sorted(cluster.shards):
        yield dagster.DynamicOutput(shard_num, mapping_key=f"shard_{shard_num}")


@frozen
class ShardResend:
    """Attach one shard's staged rows to its `sharded_events`, one team chunk at a time, then delete the originals.

    The staging table and `sharded_events` share the shard key, so every statement reads and writes local
    tables. Every statement runs on one host, because the attach table exists only there.
    """

    cluster: ClickhouseCluster
    shard_num: int
    plan: ResendPlan
    instance: dagster.DagsterInstance
    run_id: str
    log: dagster.DagsterLogManager
    query_tags: DagsterTags
    workload: Workload
    node_role: NodeRole

    def run(self) -> ShardResendTotals:
        if self.plan.config.dry_run:
            return self._count()
        check_no_other_resend_run(self.instance, self.run_id)
        host = self.cluster.any_host_in_shard_by_roles(self.shard_num, [self.node_role], self.workload)
        attach_table = ResendAttachTable(run_id=uuid.UUID(self.run_id))
        self._on_host(host, attach_table.recreate)
        try:
            totals = self._attach(host, attach_table)
        finally:
            self._on_host(host, attach_table.drop)
        self._delete_originals(host)
        return totals

    def _count(self) -> ShardResendTotals:
        columns = self._on_host(None, self.plan.table.columns)
        written = 0
        staged = 0
        for team_ids in _chunks(self.plan.team_ids, self.plan.config.team_chunk_size):
            bounds = self._staged_bounds(None, team_ids)
            if bounds is None:
                continue
            staged += bounds.rows
            chunk_written = self._execute(
                None, resend_query(self.plan.table, columns, into=None), bounds.args(team_ids)
            )
            written += chunk_written[0][0]
            self.log.info(
                f"Shard {self.shard_num}, {len(team_ids)} team(s): would write {chunk_written[0][0]} of {bounds.rows} row(s)"
            )
        return ShardResendTotals(written=written, changed_since_staging=staged - written)

    def _attach(self, host: HostInfo, attach_table: ResendAttachTable) -> ShardResendTotals:
        columns = self._on_host(host, self.plan.table.columns)
        written = 0
        staged = 0
        for team_ids in _chunks(self.plan.team_ids, self.plan.config.team_chunk_size):
            bounds = self._staged_bounds(host, team_ids)
            if bounds is None:
                continue
            staged += bounds.rows
            self._wait_for_parts_to_merge(host, bounds)
            self._execute(host, f"TRUNCATE TABLE {attach_table.qualified_name}", None)
            self._execute(
                host, resend_query(self.plan.table, columns, into=attach_table.qualified_name), bounds.args(team_ids)
            )
            # An INSERT reports the rows its MVs wrote too, so the count comes from the table.
            chunk_written = self._execute(host, f"SELECT count() FROM {attach_table.qualified_name}", None)[0][0]
            partition_ids = self._execute(
                host, f"SELECT DISTINCT _partition_id FROM {attach_table.qualified_name} ORDER BY 1", None
            )
            for (partition_id,) in partition_ids:
                self._execute(
                    host,
                    f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()} "
                    f"ATTACH PARTITION ID %(partition_id)s FROM {attach_table.qualified_name}",
                    {"partition_id": partition_id},
                )
            written += chunk_written
            self._check_no_blocking_run_started(team_ids)
            self.log.info(
                f"Shard {self.shard_num}, {len(team_ids)} team(s): wrote {chunk_written} of {bounds.rows} row(s)"
            )
        return ShardResendTotals(written=written, changed_since_staging=staged - written)

    def _delete_originals(self, host: HostInfo) -> None:
        """Delete the originals of every copy on this shard, once each replica holds the copies."""
        # An attach replicates as a REPLACE_RANGE entry. A replica that ran the delete before fetching the
        # copies would have neither row of an event for a while.
        self.cluster.map_all_hosts_in_shard(
            self.shard_num,
            tagged(
                self.query_tags,
                lambda client: client.execute(
                    f"SYSTEM SYNC REPLICA {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()} LIGHTWEIGHT"
                ),
                product=PRODUCT,
            ),
        ).result()
        runner = LightweightDeleteMutationRunner(
            EVENTS_DATA_TABLE(),
            predicate=delete_originals_predicate(self.plan.table),
            parameters={"team_ids": self.plan.team_ids},
            settings={
                **MUTATION_SETTINGS,
                "max_execution_time": self.plan.config.max_execution_time_seconds,
            },
        )
        waiter: MutationWaiter = self._on_host(host, runner)
        wait_for_mutations_on_shards(self.cluster, {self.shard_num: waiter})
        self.log.info(f"Shard {self.shard_num}: deleted the originals of the attached copies")

    def _staged_bounds(self, host: HostInfo | None, team_ids: tuple[int, ...]) -> "StagedBounds | None":
        [[timestamp_from, timestamp_to, rows]] = self._execute(
            host,
            f"SELECT min(timestamp), max(timestamp), count() FROM {self.plan.table.qualified_name} FINAL "
            "WHERE team_id IN %(team_ids)s",
            {"team_ids": team_ids},
        )
        if not rows:
            return None
        return StagedBounds(timestamp_from=timestamp_from, timestamp_to=timestamp_to, rows=rows)

    def _wait_for_parts_to_merge(self, host: HostInfo, bounds: "StagedBounds") -> None:
        if self.plan.config.max_unmerged_parts <= 0:
            return
        partitions = bounds.partitions()
        query = GET_NUM_RAW_SESSIONS_ACTIVE_PARTS(partitions, table=EVENTS_DATA_TABLE(), use_cluster=False)
        deadline = time.monotonic() + self.plan.config.parts_check_max_wait_seconds
        while True:
            active_parts = self._execute(host, query, None)[0][0]
            if active_parts < self.plan.config.max_unmerged_parts:
                return
            if time.monotonic() > deadline:
                raise dagster.Failure(
                    description=f"Stopping shard {self.shard_num}: partitions {partitions} still have "
                    f"{active_parts} active parts after {self.plan.config.parts_check_max_wait_seconds}s."
                )
            self.log.info(f"Waiting for partitions {partitions} to merge: {active_parts} active parts")
            time.sleep(self.plan.config.parts_check_poll_seconds)

    def _check_no_blocking_run_started(self, team_ids: tuple[int, ...]) -> None:
        assert self.plan.blocking_run_check is not None
        started = blocking_runs_started_since(self.instance, self.plan.blocking_run_check, self.run_id)
        if started:
            raise dagster.Failure(
                description=f"Stopping shard {self.shard_num}: {'; '.join(started)} started during the resend. "
                "A row that run removed can be back in sharded_events through a staged copy. After that run "
                f"finishes, delete the staged copies of teams {list(team_ids)} on shard {self.shard_num} "
                f"(rows of {EVENTS_DATA_TABLE()} whose (team_id, uuid, _timestamp) is in "
                f"{self.plan.table.qualified_name}), run geoip_backfill_staging_job again for those teams, "
                "and resend from the new staging table."
            )

    def _execute(self, host: HostInfo | None, query: str, args: dict[str, Any] | None) -> Any:
        config = self.plan.config
        query_settings = {
            "max_execution_time": config.max_execution_time_seconds,
            "max_memory_usage": config.max_memory_usage_bytes,
        }

        def run(client: Client) -> Any:
            return sync_execute(
                query, args, settings=query_settings, workload=self.workload, sync_client=client, flush=False
            )

        return self._on_host(host, run)

    def _on_host(self, host: HostInfo | None, fn: Callable[[Client], Any]) -> Any:
        """Run on the given host, or on any host of the shard."""
        if host is None:
            host = self.cluster.any_host_in_shard_by_roles(self.shard_num, [self.node_role], self.workload)
        return self.cluster.on_host(host, tagged(self.query_tags, fn, product=PRODUCT)).result()


@dagster.op(tags=OWNER_TAG)
def resend_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard_num: int,
    plan: ResendPlan,
) -> int:
    workload, node_role = shard_workload()
    totals = ShardResend(
        cluster=cluster,
        shard_num=shard_num,
        plan=plan,
        instance=context.instance,
        run_id=context.run_id,
        log=context.log,
        query_tags=dagster_tags(context),
        workload=workload,
        node_role=node_role,
    ).run()
    context.add_output_metadata(
        {
            "shard": dagster.MetadataValue.int(shard_num),
            "written": dagster.MetadataValue.int(totals.written),
            "changed_since_staging": dagster.MetadataValue.int(totals.changed_since_staging),
            "dry_run": dagster.MetadataValue.bool(plan.config.dry_run),
        }
    )
    return totals.written


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_resend_job() -> None:
    """Attach the staged GeoIP-enriched rows to sharded_events and delete their originals.

    Defaults to a dry run. Safe to re-run: a copy is written only while its event's newest row is the original.
    """
    plan = plan_geoip_resend()
    get_resend_shards(plan).map(lambda shard_num: resend_shard(shard_num, plan))
