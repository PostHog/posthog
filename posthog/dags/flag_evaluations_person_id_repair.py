"""Rewrite the person_id of imported flag_evaluations rows that missed a person_id rewrite.

A bulk copy into flag_evaluations can read events before a squash rewrites person_id there and
attach its rows after the squash has swept flag_evaluations. The squash then deletes the overrides
it applied, so those rows keep the merged-away person_id and no override is left for reads to
correct. This one-off job copies the current person_id from each row's events copy, through the
squash's dictionary-and-mutation lifecycle.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import dagster
import pydantic
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster
from posthog.dags.common import dagster_tags
from posthog.dags.common.dictionaries import Dictionary
from posthog.dags.common.staged_dictionary import (
    StagedDictionary,
    create_on_every_cluster,
    load_and_verify_on_every_cluster,
)
from posthog.dags.flag_evaluations_backfill import (
    COPIED_ROW_FILTER,
    GIB,
    OWNER_TAG,
    BlockingRunCheck,
    blocking_runs_started_since,
    inserted_rows,
    on_shard_host,
    resolve_backfill_days,
    shard_workload,
    wait_for_blocking_runs,
)
from posthog.dataclasses import frozen
from posthog.models.deletion_targets import FLAG_EVALUATIONS, dispatchable_here
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_SOURCE_EVENT

_TEAM_FILTER = " AND team_id IN %(team_ids)s"

_CLEANUP = "Drop this run's table and dictionary with cleanup_orphaned_flag_evaluations_person_id_repair."


class FlagEvaluationsPersonIdRepairConfig(dagster.Config):
    start_date: str | None = pydantic.Field(
        default=None,
        description="First day to repair (YYYY-MM-DD, UTC, inclusive). Same default and bounds as the flag_evaluations backfill.",
    )
    end_date: str | None = pydantic.Field(
        default=None,
        description="Day after the last day to repair (YYYY-MM-DD, UTC, exclusive). Same default and bounds as the flag_evaluations backfill.",
    )
    team_ids: list[int] | None = pydantic.Field(
        default=None, description="Repair only these teams. Leave empty to repair every team."
    )
    dry_run: bool = pydantic.Field(
        default=False,
        description="Build the repair table and report what it holds, then drop it without changing flag_evaluations.",
    )
    blocking_run_poll_seconds: int = pydantic.Field(
        default=5 * 60,
        description="How often to check again while a squash, deletes or data deletion request run is active.",
    )
    build_max_execution_time_seconds: int = pydantic.Field(
        default=30 * 60, description="ClickHouse max_execution_time for each shard's insert of one day."
    )
    build_max_memory_usage_bytes: int = pydantic.Field(
        default=32 * GIB, description="ClickHouse max_memory_usage for each shard's insert of one day."
    )
    dictionary_shards: int = pydantic.Field(default=16, description="SHARDS of the dictionary's hashed layout.")
    dictionary_max_execution_time: int = pydantic.Field(
        default=0, description="Seconds the dictionary may take to load, or 0 for no limit."
    )
    dictionary_max_memory_usage: int = pydantic.Field(
        default=0, description="Bytes the dictionary may use while it loads, or 0 for no limit."
    )


@frozen
class RepairPlan:
    days: tuple[date, ...]
    config: FlagEvaluationsPersonIdRepairConfig
    blocking_run_check: BlockingRunCheck


@frozen
class ShardRepairCounts:
    calls: int
    distinct_ids: int
    keys: int


@frozen
class RepairTableCheck:
    conflicts: int
    chains: int
    shards: dict[int, ShardRepairCounts]


@frozen
class PersonIdRepairTable:
    """Maps (team_id, distinct_id, stale_person_id) to the person_id that the row's events copy holds.

    A distinct_id that merged twice can hold two stale ids, so the stale id is part of the key.
    A key that maps to two person_ids stays as two rows, which is how the check finds it.
    """

    id: uuid.UUID

    @property
    def name(self) -> str:
        # The dictionary reads its source as dagster_dict_reader. That user can read only the tables
        # that infra grants it. The grant for the squash's snapshot tables matches this prefix.
        # The prefix also matches the snapshot glob in posthog/clickhouse/hcl/exclude.hcl.
        return f"person_distinct_id_overrides_snapshot_flag_evaluations_repair_{self.id.hex}"

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                distinct_id String,
                stale_person_id UUID,
                person_id UUID,
                shard_num UInt32,
                day Date,
                calls UInt64
            )
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.qualified_name}', '{{replica}}-{{shard}}')
            ORDER BY (team_id, distinct_id, stale_person_id, person_id, shard_num, day)
            """
        )

    def exists(self, client: Client) -> bool:
        [[count]] = client.execute(
            "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")

    def stale_keys_query(self, *, filter_team_ids: bool) -> str:
        team_filter = _TEAM_FILTER if filter_team_ids else ""
        # sharded_events and sharded_flag_evaluations share a shard key. A row's events copy is
        # therefore on its shard.
        return f"""
INSERT INTO {self.qualified_name} (team_id, distinct_id, stale_person_id, person_id, shard_num, day, calls)
SELECT f.team_id, f.distinct_id, f.person_id, e.person_id, %(shard_num)s, toDate(%(day_start)s), count()
FROM (
    SELECT team_id, uuid, distinct_id, person_id
    FROM {FLAG_EVALUATIONS_DATA_TABLE}
    WHERE timestamp >= %(day_start)s AND timestamp < %(day_end)s AND {COPIED_ROW_FILTER}{team_filter}
) AS f
INNER JOIN (
    SELECT team_id, uuid, distinct_id, person_id
    FROM {EVENTS_DATA_TABLE()}
    WHERE event = %(event)s AND timestamp >= %(day_start)s AND timestamp < %(day_end)s{team_filter}
) AS e ON f.team_id = e.team_id AND f.uuid = e.uuid AND f.distinct_id = e.distinct_id
WHERE f.person_id != e.person_id
GROUP BY f.team_id, f.distinct_id, f.person_id, e.person_id
"""

    def agreeing_calls_query(self) -> str:
        # A stale key's calls on any day may still agree with their events copies. This records
        # each such key with its own id as a second target, so the check fails it instead of the
        # mutation rewriting the agreeing calls. Both sides read only the shard's stale keys.
        stale_keys = (
            f"SELECT team_id, distinct_id, stale_person_id FROM {self.qualified_name} "
            "WHERE shard_num = %(shard_num)s AND person_id != stale_person_id"
        )
        return f"""
INSERT INTO {self.qualified_name} (team_id, distinct_id, stale_person_id, person_id, shard_num, day, calls)
SELECT f.team_id, f.distinct_id, f.person_id, f.person_id, %(shard_num)s, toDate(%(day_start)s), count()
FROM (
    SELECT team_id, uuid, distinct_id, person_id
    FROM {FLAG_EVALUATIONS_DATA_TABLE}
    WHERE timestamp >= %(day_start)s AND timestamp < %(day_end)s AND {COPIED_ROW_FILTER}
        AND (team_id, distinct_id, person_id) IN ({stale_keys})
) AS f
INNER JOIN (
    SELECT team_id, uuid, distinct_id, person_id
    FROM {EVENTS_DATA_TABLE()}
    WHERE event = %(event)s AND timestamp >= %(day_start)s AND timestamp < %(day_end)s
        AND (team_id, distinct_id) IN (SELECT team_id, distinct_id FROM ({stale_keys}))
) AS e ON f.team_id = e.team_id AND f.uuid = e.uuid AND f.distinct_id = e.distinct_id
WHERE f.person_id = e.person_id
GROUP BY f.team_id, f.distinct_id, f.person_id
"""


@frozen
class PersonIdRepairDictionary(Dictionary):
    source: PersonIdRepairTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def schema(self) -> str:
        return "team_id Int64, distinct_id String, stale_person_id UUID, person_id UUID"

    @property
    def primary_key(self) -> str:
        return "team_id, distinct_id, stale_person_id"

    @property
    def query(self) -> str:
        # The check proves one person_id per key before this loads. any() is therefore exact.
        return (
            f"SELECT team_id, distinct_id, stale_person_id, any(person_id) AS person_id "
            f"FROM {self.source.qualified_name} GROUP BY team_id, distinct_id, stale_person_id"
        )

    def staged(self) -> StagedDictionary:
        return StagedDictionary(
            key=f"{self.name}.parquet",
            columns="team_id, distinct_id, stale_person_id, person_id",
            structure=self.schema,
        )

    def update_command(self, *, filter_team_ids: bool) -> str:
        # The key includes the row's current person_id. A row matches only while it still holds the
        # stale id. A rerun therefore changes nothing. A row that a later squash moved stays where it is.
        # The build checked only the rows inside the window, so the mutation stays inside it too.
        team_filter = _TEAM_FILTER if filter_team_ids else ""
        return (
            "UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id, person_id)) "
            "WHERE timestamp >= %(window_start)s AND timestamp < %(window_end)s "
            f"AND {COPIED_ROW_FILTER} AND dictHas(%(name)s, (team_id, distinct_id, person_id)){team_filter}"
        )


@dagster.op(tags=OWNER_TAG)
def plan_person_id_repair(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: FlagEvaluationsPersonIdRepairConfig,
) -> RepairPlan:
    """Resolve the days, then wait until no squash, deletes or data deletion request run is active.

    The build reads person_id from events, so the watermark taken here covers it as well as the mutation.
    """
    if not dispatchable_here(cluster, FLAG_EVALUATIONS):
        raise dagster.Failure(description=f"{FLAG_EVALUATIONS_DATA_TABLE} does not exist on this cluster.")
    days = resolve_backfill_days(start_date=config.start_date, end_date=config.end_date, today=datetime.now(UTC).date())
    check = wait_for_blocking_runs(context.instance, context.run_id, context.log, config.blocking_run_poll_seconds)
    context.log.info(f"Repairing {len(days)} day(s), newest first, from {days[0]} back to {days[-1]}")
    return RepairPlan(days=days, config=config, blocking_run_check=check)


@dagster.op(tags=OWNER_TAG)
def create_repair_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: RepairPlan,
) -> PersonIdRepairTable:
    table = PersonIdRepairTable(id=uuid.UUID(context.run.run_id))
    cluster.map_all_hosts(table.create).result()
    return table


@dagster.op(out=dagster.DynamicOut(int), tags=OWNER_TAG)
def get_repair_shards(
    cluster: dagster.ResourceParam[ClickhouseCluster], table: PersonIdRepairTable
) -> Iterator[dagster.DynamicOutput[int]]:
    """Fan out one build op per shard, so a failed shard can be re-executed on its own from the UI."""
    for shard_num in sorted(cluster.shards):
        yield dagster.DynamicOutput(shard_num, mapping_key=f"shard_{shard_num}")


@dagster.op(tags=OWNER_TAG)
def build_repair_shard(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard_num: int,
    plan: RepairPlan,
    table: PersonIdRepairTable,
) -> int:
    """Insert this shard's stale keys one day per query, then the keys whose calls also agree with events.

    A rerun inserts the same rows, which the table collapses.
    """
    config = plan.config
    workload, node_role = shard_workload()
    stale_keys_query = table.stale_keys_query(filter_team_ids=bool(config.team_ids))
    agreeing_calls_query = table.agreeing_calls_query()
    query_settings = {
        "max_execution_time": config.build_max_execution_time_seconds,
        "max_memory_usage": config.build_max_memory_usage_bytes,
    }

    def day_args(day: date) -> dict[str, Any]:
        return {
            "shard_num": shard_num,
            "event": FLAG_EVALUATIONS_SOURCE_EVENT,
            "day_start": f"{day:%Y-%m-%d} 00:00:00",
            "day_end": f"{day + timedelta(days=1):%Y-%m-%d} 00:00:00",
            "team_ids": tuple(config.team_ids or ()),
        }

    def insert(query: str, day: date, client: Client) -> int:
        return inserted_rows(
            sync_execute(query, day_args(day), settings=query_settings, workload=workload, sync_client=client)
        )

    def insert_agreeing_calls(client: Client) -> int:
        # The stale keys came from inserts on any replica. The sync makes this host read all of them.
        table.sync(client)
        return sum(insert(agreeing_calls_query, day, client) for day in plan.days)

    def on_this_shard(fn: Callable[[Client], int]) -> int:
        return on_shard_host(cluster, shard_num, fn, dagster_tags(context), workload, node_role)

    stale_keys = 0
    for day in plan.days:
        keys = on_this_shard(partial(insert, stale_keys_query, day))
        stale_keys += keys
        context.log.info(f"Shard {shard_num}, {day}: {keys} stale key(s)")
    agreeing_keys = on_this_shard(insert_agreeing_calls)
    context.log.info(f"Shard {shard_num}: {agreeing_keys} stale key-day(s) with calls that agree with events")
    context.add_output_metadata(
        {
            "shard": dagster.MetadataValue.int(shard_num),
            "keys": dagster.MetadataValue.int(stale_keys),
            "agreeing": dagster.MetadataValue.int(agreeing_keys),
        }
    )
    return stale_keys


@dagster.op(tags=OWNER_TAG)
def check_repair_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonIdRepairTable,
    built_shards: list[int],
) -> PersonIdRepairTable:
    """Fail unless each key maps to one person_id that is not itself a stale key, and report what the table holds.

    The report counts the calls the build joined. The mutation changes fewer if a squash moves a row first.
    """
    cluster.map_all_hosts(table.sync).result()

    def read(client: Client) -> RepairTableCheck:
        [[conflicts]] = client.execute(
            f"""
            SELECT count() FROM (
                SELECT 1 FROM {table.qualified_name}
                GROUP BY team_id, distinct_id, stale_person_id
                HAVING uniqExact(person_id) > 1
            )
            """
        )
        # A target that is also a stale key would move a row once per run instead of once in total.
        # A key that maps to its own id comes from the agreeing-calls pass and already counts as a conflict.
        [[chains]] = client.execute(
            f"""
            SELECT count() FROM (
                SELECT DISTINCT team_id, distinct_id, person_id FROM {table.qualified_name}
                WHERE person_id != stale_person_id
            )
            WHERE (team_id, distinct_id, person_id) IN (
                SELECT team_id, distinct_id, stale_person_id FROM {table.qualified_name}
            )
            """
        )
        shards = {
            shard: ShardRepairCounts(calls=calls, distinct_ids=distinct_ids, keys=keys)
            for shard, calls, distinct_ids, keys in client.execute(
                f"""
                SELECT shard_num, sum(calls), uniqExact(team_id, distinct_id), uniqExact(team_id, distinct_id, stale_person_id)
                FROM {table.qualified_name} FINAL
                GROUP BY shard_num
                """
            )
        }
        return RepairTableCheck(conflicts=conflicts, chains=chains, shards=shards)

    check = cluster.any_host(read).result()
    report = {
        f"shard_{shard}": {"calls": counts.calls, "distinct_ids": counts.distinct_ids, "keys": counts.keys}
        for shard, counts in sorted(check.shards.items())
    }
    context.add_output_metadata(
        {
            **{
                total: dagster.MetadataValue.int(sum(counts[total] for counts in report.values()))
                for total in ("calls", "distinct_ids", "keys")
            },
            "per_shard": dagster.MetadataValue.json(report),
            "conflicts": dagster.MetadataValue.int(check.conflicts),
            "chains": dagster.MetadataValue.int(check.chains),
        }
    )
    if check.conflicts or check.chains:
        raise dagster.Failure(
            description=f"{table.qualified_name} has {check.conflicts} key(s) that map to more than one person_id and "
            f"{check.chains} target(s) that are also stale keys. Inspect the table. {_CLEANUP}"
        )
    return table


@dagster.op(tags=OWNER_TAG)
def create_repair_dictionary(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: RepairPlan,
    table: PersonIdRepairTable,
) -> PersonIdRepairDictionary:
    dictionary = PersonIdRepairDictionary(source=table)
    create_on_every_cluster(
        context,
        [cluster],
        dictionary,
        shards=plan.config.dictionary_shards,
        max_execution_time=plan.config.dictionary_max_execution_time,
        max_memory_usage=plan.config.dictionary_max_memory_usage,
    )
    return dictionary


@dagster.op(tags=OWNER_TAG)
def load_and_verify_repair_dictionary(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonIdRepairDictionary,
) -> PersonIdRepairDictionary:
    load_and_verify_on_every_cluster([cluster], dictionary)

    def read_size(client: Client) -> dict[str, int]:
        [[elements, bytes_allocated]] = client.execute(
            "SELECT element_count, bytes_allocated FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": dictionary.name},
        )
        return {"elements": elements, "bytes_allocated": bytes_allocated}

    context.add_output_metadata(
        {name: dagster.MetadataValue.int(value) for name, value in cluster.any_host(read_size).result().items()}
    )
    return dictionary


@dagster.op(tags=OWNER_TAG)
def run_repair_mutation(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    plan: RepairPlan,
    dictionary: PersonIdRepairDictionary,
) -> PersonIdRepairDictionary:
    """Rewrite the stale rows on every shard.

    Fail before the mutation if a blocking run started since the plan's watermark, and again after it.
    """
    if plan.config.dry_run:
        context.log.info("Dry run: leaving flag_evaluations unchanged")
        return dictionary

    def blocking_runs_started() -> str:
        return "; ".join(blocking_runs_started_since(context.instance, plan.blocking_run_check, context.run_id))

    if started := blocking_runs_started():
        cluster.map_all_hosts(dictionary.drop).result()
        cluster.map_all_hosts(dictionary.source.drop).result()
        raise dagster.Failure(
            description=f"{started} started after the repair read person_id from events. "
            f"{FLAG_EVALUATIONS_DATA_TABLE} is unchanged, and this run dropped its table and dictionary. "
            "Run the repair again after that run finishes."
        )

    team_ids = plan.config.team_ids
    AlterTableMutationRunner(
        table=FLAG_EVALUATIONS_DATA_TABLE,
        commands={dictionary.update_command(filter_team_ids=bool(team_ids))},
        parameters={
            "name": dictionary.qualified_name,
            "team_ids": tuple(team_ids or ()),
            "window_start": f"{min(plan.days):%Y-%m-%d} 00:00:00",
            "window_end": f"{max(plan.days) + timedelta(days=1):%Y-%m-%d} 00:00:00",
        },
    ).run_on_shards(cluster)

    if started := blocking_runs_started():
        raise dagster.Failure(
            description=f"{started} started during the repair mutation. A deletion that reached "
            f"{FLAG_EVALUATIONS_DATA_TABLE} before the mutation did not match rows that still held a stale "
            f"person_id, and the mutation then gave them the deleted person's id. Check what that run deleted. {_CLEANUP}"
        )
    return dictionary


@dagster.op(tags=OWNER_TAG)
def drop_repair_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster], dictionary: PersonIdRepairDictionary
) -> PersonIdRepairTable:
    cluster.map_all_hosts(dictionary.drop).result()
    return dictionary.source


@dagster.op(tags=OWNER_TAG)
def drop_repair_table(cluster: dagster.ResourceParam[ClickhouseCluster], table: PersonIdRepairTable) -> None:
    cluster.map_all_hosts(table.drop).result()


@dagster.job(tags=OWNER_TAG)
def flag_evaluations_person_id_repair_job() -> None:
    """Give imported flag_evaluations rows the person_id of their events copy, where the two differ.

    Only rows that match the backfill's copied-row filter and still hold the stale id change, so a
    rerun changes nothing.
    """
    plan = plan_person_id_repair()
    table = create_repair_table(plan)
    built_shards = get_repair_shards(table).map(lambda shard_num: build_repair_shard(shard_num, plan, table))
    checked_table = check_repair_table(table, built_shards.collect())
    dictionary = load_and_verify_repair_dictionary(create_repair_dictionary(plan, checked_table))
    drop_repair_table(drop_repair_dictionary(run_repair_mutation(plan, dictionary)))


class RepairRunConfig(dagster.Config):
    run_id: str = pydantic.Field(description="The ID of the repair run whose table and dictionary to drop.")


@dagster.op(tags=OWNER_TAG)
def get_repair_dictionary_for_run(config: RepairRunConfig) -> PersonIdRepairDictionary:
    """A handle to a repair run's dictionary. It does not check that the dictionary or its table exists."""
    return PersonIdRepairDictionary(source=PersonIdRepairTable(id=uuid.UUID(config.run_id)))


@dagster.op(tags=OWNER_TAG)
def check_no_repair_mutation_running(
    cluster: dagster.ResourceParam[ClickhouseCluster], dictionary: PersonIdRepairDictionary
) -> PersonIdRepairDictionary:
    """Fail while a mutation that reads this dictionary is unfinished on any host.

    A stopped Dagster run leaves its ClickHouse mutation running. Dropping the dictionary under it
    fails the mutation's remaining parts, and the failed mutation then blocks later mutations on the table.
    """

    def running(client: Client) -> int:
        [[count]] = client.execute(
            """
            SELECT count() FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND NOT is_done AND NOT is_killed
                AND position(command, %(name)s) > 0
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": FLAG_EVALUATIONS_DATA_TABLE,
                "name": dictionary.qualified_name,
            },
        )
        return count

    hosts = [host.connection_info.host for host, count in cluster.map_all_hosts(running).result().items() if count]
    if hosts:
        raise dagster.Failure(
            description=f"A mutation that reads {dictionary.qualified_name} is unfinished on {', '.join(hosts)}. "
            "Wait for it to finish, or stop it with KILL MUTATION, then run the cleanup again."
        )
    return dictionary


@dagster.job(tags=OWNER_TAG)
def cleanup_orphaned_flag_evaluations_person_id_repair() -> None:
    """Drop the table and dictionary that a failed repair run left, once its mutation has finished or been killed."""
    drop_repair_table(drop_repair_dictionary(check_no_repair_mutation_running(get_repair_dictionary_for_run())))
