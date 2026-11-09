"""Write the rows a geoip_backfill_staging_job run staged back into the events tables.

Each staged row has the sort key of its original and a newer `_timestamp`, so the ReplacingMergeTree
`sharded_events` keeps only the staged row once the two land in the same merge. Until that merge, a
query without FINAL counts the event twice. The MVs on `sharded_events` fire on the insert:

- `raw_sessions_v3` aggregates with uniq and argMin, so a second copy changes no count and fills the GeoIP
  columns of a session whose events had none. `raw_sessions` (v2) does the same, except that its
  `*_count` sums add the copy a second time. Its `*_uniq` columns do not change.
- `events_recent` sorts on `inserted_at`, so its copy of the staged row never collapses with the
  original. That table keeps both until its TTL drops them.

`events_json` reads Kafka, not `sharded_events`, so this job does not repair it.
"""

import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.dags.common import dagster_tags
from posthog.dags.common.dictionaries import Dictionary
from posthog.dags.common.staged_dictionary import (
    StagedDictionary,
    create_on_every_cluster,
    load_and_verify_on_every_cluster,
)
from posthog.dags.flag_evaluations_backfill import (
    BlockingRunCheck,
    blocking_runs_started_since,
    shard_workload,
    wait_for_blocking_runs,
)
from posthog.dags.geoip_backfill import OWNER_TAG, EventColumn, GeoipStagingTable, on_shard_host, tagged
from posthog.dataclasses import frozen
from posthog.models.ai_events.sql import (
    DATA_TABLE_NAME as AI_EVENTS_DATA_TABLE,
    _strip_heavy_properties_sql,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.raw_sessions.sessions_v3 import GET_NUM_RAW_SESSIONS_ACTIVE_PARTS

GIB = 1024**3

_AI_EVENT_FILTER = "startsWith(event, '$ai_')"


class GeoipResendConfig(dagster.Config):
    staging_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_staging_job run to resend.")
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Resend only these teams. Leave empty to resend every staged team."
    )
    dry_run: bool = pydantic.Field(
        default=True, description="Count the rows each team chunk would write, and write nothing."
    )
    include_ai_events: bool = pydantic.Field(
        default=False, description="Also rewrite the properties of the staged AI events in sharded_ai_events."
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


@frozen
class ShardResendTotals:
    written: int
    changed_since_staging: int


def resend_query(table: GeoipStagingTable, columns: Sequence[EventColumn], *, count_only: bool) -> str:
    """Copy the staged rows of a team chunk whose original still holds what staging read.

    A deletion request or a person squash that changed the original after staging would be undone by the
    staged copy, so such a row stays out. After a merge drops the original, nothing matches, which makes a
    re-run write nothing.
    """
    staged_columns = ", ".join(f"s.{column.quoted}" for column in columns)
    select = f"""
        SELECT {"count()" if count_only else staged_columns}
        FROM {table.qualified_name} AS s FINAL
        INNER JOIN (
            SELECT DISTINCT team_id, uuid, properties, person_id
            FROM {EVENTS_DATA_TABLE()}
            WHERE team_id IN %(team_ids)s
                AND timestamp >= %(timestamp_from)s AND timestamp <= %(timestamp_to)s
                AND uuid IN (SELECT uuid FROM {table.qualified_name} WHERE team_id IN %(team_ids)s)
        ) AS e ON s.team_id = e.team_id AND s.uuid = e.uuid
        WHERE s.team_id IN %(team_ids)s
            AND e.properties = s.original_properties
            AND e.person_id = s.person_id
    """
    if count_only:
        return select
    column_list = ", ".join(column.quoted for column in columns)
    return f"INSERT INTO {EVENTS_DATA_TABLE()} ({column_list}) {select}"


def _chunks(items: Sequence[int], size: int) -> Iterator[tuple[int, ...]]:
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


@dagster.op(tags=OWNER_TAG)
def plan_geoip_resend(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: GeoipResendConfig,
) -> ResendPlan:
    """Read the staged teams, then wait until no squash, deletes or data deletion request run is active."""
    table = GeoipStagingTable(id=uuid.UUID(config.staging_run_id))
    if not cluster.any_host_by_role(table.exists, NodeRole.DATA).result():
        raise dagster.Failure(description=f"{table.qualified_name} does not exist.")

    def staged_teams(client: Client) -> list[tuple[int]]:
        return client.execute(f"SELECT DISTINCT team_id FROM {table.qualified_name}")

    team_ids = {
        team_id for rows in cluster.map_one_host_per_shard(staged_teams).result().values() for (team_id,) in rows
    }
    if config.team_ids:
        team_ids &= set(config.team_ids)
    check = None
    if not config.dry_run:
        check = wait_for_blocking_runs(context.instance, context.run_id, context.log, config.blocking_run_poll_seconds)
    context.log.info(f"Resending {len(team_ids)} team(s) from {table.qualified_name}")
    return ResendPlan(table=table, team_ids=tuple(sorted(team_ids)), config=config, blocking_run_check=check)


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_resend_shards(
    cluster: dagster.ResourceParam[ClickhouseCluster], plan: ResendPlan
) -> Iterator[dagster.DynamicOutput[int]]:
    """Fan out one op per shard, so a failed shard can be re-executed on its own from the UI."""
    for shard_num in sorted(cluster.shards):
        yield dagster.DynamicOutput(shard_num, mapping_key=f"shard_{shard_num}")


@frozen
class ShardResend:
    """Insert one shard's staged rows into its `sharded_events`, one team chunk at a time.

    The staging table and `sharded_events` share the shard key, so the insert reads and writes local tables.
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
        columns = self._on_shard(self.plan.table.columns)
        dry_run = self.plan.config.dry_run
        written = 0
        staged = 0
        for team_ids in _chunks(self.plan.team_ids, self.plan.config.team_chunk_size):
            bounds = self._staged_bounds(team_ids)
            if bounds is None:
                continue
            staged += bounds.rows
            if not dry_run:
                self._wait_for_parts_to_merge(bounds)
            args = {
                "team_ids": team_ids,
                "timestamp_from": f"{bounds.timestamp_from:%Y-%m-%d %H:%M:%S.%f}",
                "timestamp_to": f"{bounds.timestamp_to:%Y-%m-%d %H:%M:%S.%f}",
            }
            # An INSERT reports the rows the MVs on sharded_events wrote too, so the count comes from the SELECT.
            chunk_written = self._execute(resend_query(self.plan.table, columns, count_only=True), args)[0][0]
            if chunk_written and not dry_run:
                self._execute(resend_query(self.plan.table, columns, count_only=False), args)
            written += chunk_written
            if not dry_run:
                self._check_no_blocking_run_started(team_ids)
            action = "would write" if dry_run else "wrote"
            self.log.info(
                f"Shard {self.shard_num}, {len(team_ids)} team(s): {action} {chunk_written} of {bounds.rows} row(s)"
            )
        return ShardResendTotals(written=written, changed_since_staging=staged - written)

    def _staged_bounds(self, team_ids: tuple[int, ...]) -> StagedBounds | None:
        [[timestamp_from, timestamp_to, rows]] = self._execute(
            f"SELECT min(timestamp), max(timestamp), count() FROM {self.plan.table.qualified_name} FINAL "
            "WHERE team_id IN %(team_ids)s",
            {"team_ids": team_ids},
        )
        if not rows:
            return None
        return StagedBounds(timestamp_from=timestamp_from, timestamp_to=timestamp_to, rows=rows)

    def _wait_for_parts_to_merge(self, bounds: "StagedBounds") -> None:
        if self.plan.config.max_unmerged_parts <= 0:
            return
        partitions = bounds.partitions()
        query = GET_NUM_RAW_SESSIONS_ACTIVE_PARTS(partitions, table=EVENTS_DATA_TABLE(), use_cluster=False)
        deadline = time.monotonic() + self.plan.config.parts_check_max_wait_seconds
        while True:
            active_parts = self._execute(query, None)[0][0]
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

    def _execute(self, query: str, args: dict[str, Any] | None) -> Any:
        config = self.plan.config
        query_settings = {
            "max_execution_time": config.max_execution_time_seconds,
            "max_memory_usage": config.max_memory_usage_bytes,
        }

        def run(client: Client) -> Any:
            return sync_execute(
                query, args, settings=query_settings, workload=self.workload, sync_client=client, flush=False
            )

        return self._on_shard(run)

    def _on_shard(self, fn: Callable[[Client], Any]) -> Any:
        return on_shard_host(self.cluster, self.shard_num, fn, self.query_tags, self.workload, self.node_role)


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


@frozen
class AiEventsPatchTable:
    """The new and original properties of the staged AI events, on every host of the AI events cluster.

    The AI events table shards on the trace, not the distinct ID, so its rows sit on other shards than
    their events copies. The patch rows therefore go to one replicated table that every host reads.
    """

    id: uuid.UUID

    @property
    def name(self) -> str:
        # Matches the "tmp_*" glob in posthog/clickhouse/hcl/exclude.hcl.
        return f"tmp_geoip_backfill_ai_{self.id.hex}"

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        engine = ReplacingMergeTree(self.name, ver="version", replication_scheme=ReplicationScheme.REPLICATED)
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                uuid UUID,
                properties String,
                original_properties String,
                version UInt64
            )
            ENGINE = {engine}
            ORDER BY (team_id, uuid)
            """
        )

    def insert(self, rows: Sequence[tuple[Any, ...]], client: Client) -> None:
        client.execute(
            f"INSERT INTO {self.qualified_name} (team_id, uuid, properties, original_properties, version) VALUES",
            [(*row, 0) for row in rows],
        )

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")


@frozen
class AiEventsPatchDictionary(Dictionary):
    source: AiEventsPatchTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def schema(self) -> str:
        return "team_id Int64, uuid UUID, properties String, original_properties String"

    @property
    def primary_key(self) -> str:
        return "team_id, uuid"

    @property
    def query(self) -> str:
        return f"SELECT team_id, uuid, properties, original_properties FROM {self.source.qualified_name} FINAL"

    def staged(self) -> StagedDictionary:
        return StagedDictionary(
            key=f"{self.name}.parquet",
            columns="team_id, uuid, properties, original_properties",
            structure=self.schema,
        )

    def update_command(self) -> str:
        # Only a row that still holds the properties its events copy had at staging changes, so a re-run
        # changes nothing and a row that a deletion request rewrote since keeps that rewrite.
        return (
            "UPDATE properties = dictGetString(%(name)s, 'properties', (team_id, uuid)) "
            "WHERE team_id IN %(team_ids)s AND dictHas(%(name)s, (team_id, uuid)) "
            "AND properties = dictGetString(%(name)s, 'original_properties', (team_id, uuid))"
        )


def ai_events_patch_rows(table: GeoipStagingTable, team_ids: tuple[int, ...], client: Client) -> list[tuple[Any, ...]]:
    """The properties the AI events MV would write for each staged AI event, before and after the repair."""
    return client.execute(
        f"""
        SELECT team_id, uuid, {_strip_heavy_properties_sql("properties")}, {_strip_heavy_properties_sql("original_properties")}
        FROM {table.qualified_name} FINAL
        WHERE team_id IN %(team_ids)s AND {_AI_EVENT_FILTER}
        """,
        {"team_ids": team_ids},
    )


@dagster.op(tags=OWNER_TAG)
def repair_ai_events(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: ResendPlan,
    resent_shards: list[int],
) -> None:
    """Rewrite the properties of the staged AI events in place.

    `sharded_ai_events` is a plain MergeTree, so an insert would keep both copies. A mutation rewrites
    the parts that hold the rows instead. TODO(team-clickhouse): confirm a mutation is acceptable on
    `sharded_ai_events`, and grant dagster_dict_reader SELECT on `tmp_geoip_backfill_ai_*` on the AI events
    cluster, which the dictionary reads.
    """
    if not plan.config.include_ai_events:
        context.log.info("include_ai_events is off: leaving sharded_ai_events unchanged")
        return
    query_tags = dagster_tags(context)
    rows: list[tuple[Any, ...]] = []
    for shard_rows in (
        cluster.map_one_host_per_shard(tagged(query_tags, partial(ai_events_patch_rows, plan.table, plan.team_ids)))
        .result()
        .values()
    ):
        rows.extend(shard_rows)
    per_team = Counter(row[0] for row in rows)
    context.add_output_metadata(
        {
            "ai_events": dagster.MetadataValue.int(len(rows)),
            "teams": dagster.MetadataValue.int(len(per_team)),
            "dry_run": dagster.MetadataValue.bool(plan.config.dry_run),
        }
    )
    if plan.config.dry_run or not rows:
        context.log.info(f"Would rewrite {len(rows)} AI event(s) in {len(per_team)} team(s)")
        return

    ai_cluster = cluster.sibling(settings.CLICKHOUSE_AI_EVENTS_CLUSTER)
    patch_table = AiEventsPatchTable(id=uuid.UUID(context.run_id))
    dictionary = AiEventsPatchDictionary(source=patch_table)
    ai_cluster.map_all_hosts(patch_table.create).result()
    ai_cluster.any_host(partial(patch_table.insert, rows)).result()
    ai_cluster.map_all_hosts(patch_table.sync).result()
    create_on_every_cluster(context, [ai_cluster], dictionary, shards=1, max_execution_time=0, max_memory_usage=0)
    load_and_verify_on_every_cluster([ai_cluster], dictionary)
    AlterTableMutationRunner(
        table=AI_EVENTS_DATA_TABLE,
        commands={dictionary.update_command()},
        parameters={"name": dictionary.qualified_name, "team_ids": tuple(per_team)},
    ).run_on_shards(ai_cluster)
    ai_cluster.map_all_hosts(dictionary.drop).result()
    ai_cluster.map_all_hosts(patch_table.drop).result()
    context.log.info(f"Rewrote up to {len(rows)} AI event(s) in {len(per_team)} team(s)")


@dagster.job(tags=OWNER_TAG)
def geoip_backfill_resend_job() -> None:
    """Insert the staged GeoIP-enriched rows into sharded_events, and optionally rewrite the AI events.

    Defaults to a dry run. Safe to re-run: a row is written only while its original still holds what staging read.
    """
    plan = plan_geoip_resend()
    resent = get_resend_shards(plan).map(lambda shard_num: resend_shard(shard_num, plan))
    repair_ai_events(plan, resent.collect())


class ResendRunConfig(dagster.Config):
    resend_run_id: str = pydantic.Field(description="The ID of the geoip_backfill_resend_job run to clean up after.")


@dagster.op(tags=OWNER_TAG)
def drop_ai_events_patch(cluster: dagster.ResourceParam[ClickhouseCluster], config: ResendRunConfig) -> None:
    """Drop the AI events patch dictionary and table of a resend run, once no mutation reads them."""
    ai_cluster = cluster.sibling(settings.CLICKHOUSE_AI_EVENTS_CLUSTER)
    patch_table = AiEventsPatchTable(id=uuid.UUID(config.resend_run_id))
    dictionary = AiEventsPatchDictionary(source=patch_table)

    def running(client: Client) -> int:
        [[count]] = client.execute(
            """
            SELECT count() FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND NOT is_done AND NOT is_killed
                AND position(command, %(name)s) > 0
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": AI_EVENTS_DATA_TABLE,
                "name": dictionary.qualified_name,
            },
        )
        return count

    hosts = [host.connection_info.host for host, count in ai_cluster.map_all_hosts(running).result().items() if count]
    if hosts:
        raise dagster.Failure(
            description=f"A mutation that reads {dictionary.qualified_name} is unfinished on {', '.join(hosts)}. "
            "Wait for it to finish, or stop it with KILL MUTATION, then run the cleanup again."
        )
    ai_cluster.map_all_hosts(dictionary.drop).result()
    ai_cluster.map_all_hosts(patch_table.drop).result()


@dagster.job(tags=OWNER_TAG)
def cleanup_geoip_backfill_resend() -> None:
    """Drop what a failed geoip_backfill_resend_job run left on the AI events cluster."""
    drop_ai_events_patch()
