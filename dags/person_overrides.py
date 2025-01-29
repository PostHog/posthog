import time
import uuid
from dataclasses import dataclass
from functools import partial, reduce

import dagster
import pydantic
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    Mutation,
    MutationRunner,
    get_cluster,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE


class ClickhouseClusterResource(dagster.ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "receive_timeout": f"{10 * 60}",  # some queries like dictionary checksumming can be very slow
    }

    def create_resource(self, context: dagster.InitResourceContext) -> ClickhouseCluster:
        return get_cluster(context.log, client_settings=self.client_settings)


@dataclass
class PersonOverridesSnapshotTable:
    id: uuid.UUID

    @property
    def name(self) -> str:
        return f"person_distinct_id_overrides_snapshot_{self.id.hex}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (team_id Int64, distinct_id String, person_id UUID, version Int64)
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.qualified_name}', '{{replica}}-{{shard}}', version)
            ORDER BY (team_id, distinct_id)
            """
        )

    def exists(self, client: Client) -> None:
        results = client.execute(
            f"SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def populate(self, client: Client, timestamp: str, limit: int | None = None) -> None:
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        # this could optionally support truncate as a config option if necessary to reset the table state, or
        # force an optimize after insertion to compact the table before dictionary insertion (if that's even needed)
        [[count]] = client.execute(f"SELECT count() FROM {self.qualified_name}")
        assert count == 0

        limit_clause = f"LIMIT {limit}" if limit else ""

        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (team_id, distinct_id, person_id, version)
            SELECT team_id, distinct_id, argMax(person_id, version), max(version)
            FROM {settings.CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_ID_OVERRIDES_TABLE}
            WHERE _timestamp < %(timestamp)s
            GROUP BY team_id, distinct_id
            {limit_clause}
            """,
            {"timestamp": timestamp},
            settings={
                "optimize_aggregation_in_order": 1,  # slows down the query, but reduces memory consumption dramatically
            },
        )

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")

        # this is probably excessive (and doesn't guarantee that anybody else won't mess with the table later) but it
        # probably doesn't hurt to be careful
        [[queue_size]] = client.execute(
            "SELECT queue_size FROM system.replicas WHERE database = %(database)s AND table = %(table)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.name},
        )
        assert queue_size == 0


@dataclass
class PersonOverridesSnapshotDictionary:
    source: PersonOverridesSnapshotTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                distinct_id String,
                person_id UUID,
                version Int64
            )
            PRIMARY KEY team_id, distinct_id
            SOURCE(CLICKHOUSE(DB %(database)s TABLE %(table)s PASSWORD %(password)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": self.source.name,
                "password": settings.CLICKHOUSE_PASSWORD,
            },
        )

    def exists(self, client: Client) -> bool:
        results = client.execute(
            "SELECT count() FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP DICTIONARY IF EXISTS {self.qualified_name} SYNC")

    def __is_loaded(self, client: Client) -> bool:
        results = client.execute(
            "SELECT status, last_exception FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        if not results:
            raise Exception("dictionary does not exist")
        else:
            [[status, last_exception]] = results
            if status == "LOADED":
                return True
            elif status in {"LOADING", "FAILED_AND_RELOADING", "LOADED_AND_RELOADING"}:
                return False
            elif status == "FAILED":
                raise Exception(f"failed to load: {last_exception}")
            else:
                raise Exception(f"unexpected status: {status}")

    def load(self, client: Client):
        # TODO: this should probably not reload if the dictionary is already loaded
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")

        # reload is async, so we need to wait for the dictionary to actually be loaded
        # TODO: this should probably throw on unexpected reloads
        while not self.__is_loaded(client):
            time.sleep(5.0)

        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, distinct_id)
            """
        )
        [[checksum]] = results
        return checksum

    @property
    def person_id_update_mutation_runner(self) -> MutationRunner:
        return MutationRunner(
            EVENTS_DATA_TABLE(),
            f"""
            UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id))
            WHERE dictHas(%(name)s, (team_id, distinct_id))
            """,
            {"name": self.qualified_name},
        )

    @property
    def overrides_delete_mutation_runner(self) -> MutationRunner:
        return MutationRunner(
            PERSON_DISTINCT_ID_OVERRIDES_TABLE,
            f"""
            DELETE WHERE
                isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version)
                AND snapshot_version >= version
            """,
            {"name": self.qualified_name},
        )


# Snapshot Table Management


@dagster.op
def create_snapshot_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PersonOverridesSnapshotTable:
    """Create the snapshot table on all hosts in the cluster."""
    table = PersonOverridesSnapshotTable(id=uuid.UUID(context.run.run_id))
    cluster.map_all_hosts(table.create).result()
    return table


class PopulateSnapshotTableConfig(dagster.Config):
    """
    Configuration for creating and populating the initial snapshot table.
    """

    timestamp: str = pydantic.Field(
        description="The upper bound (non-inclusive) timestamp used when selecting person overrides to be squashed. The "
        "value can be provided in any format that is can be parsed by ClickHouse. This value should be far enough in "
        "the past that there is no reasonable likelihood that events or overrides prior to this time have not yet been "
        "written to the database and replicated to all hosts in the cluster."
    )
    limit: int | None = pydantic.Field(
        description="The number of rows to include in the snapshot. If provided, this can be used to limit the total "
        "amount of memory consumed by the squash process during execution."
    )


@dagster.op
def populate_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
    config: PopulateSnapshotTableConfig,
) -> PersonOverridesSnapshotTable:
    """Fill the snapshot data with the selected overrides based on the configuration timestamp."""
    cluster.any_host(partial(table.populate, timestamp=config.timestamp, limit=config.limit)).result()
    return table


@dagster.op
def wait_for_snapshot_table_replication(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotTable:
    """Wait for the snapshot table data to be replicated to all hosts in the cluster."""
    cluster.map_all_hosts(table.sync).result()
    return table


# Snapshot Dictionary Management


class SnapshotDictionaryConfig(dagster.Config):
    shards: int = pydantic.Field(
        default=16,
        description="The number of shards to be used when building the dictionary. Using larger values can speed up the "
        "creation process. See the ClickHouse documentation for more information.",
    )
    max_execution_time: int = pydantic.Field(
        default=0,
        description="The maximum amount of time to wait for the dictionary to be loaded before considering the operation "
        "a failure, or 0 to wait an unlimited amount of time.",
    )
    max_memory_usage: int = pydantic.Field(
        default=0,
        description="The maximum amount of memory to use for the dictionary, or 0 to use an unlimited amount.",
    )


@dagster.op
def create_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: SnapshotDictionaryConfig,
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotDictionary:
    """Create the snapshot dictionary (from the snapshot table data) on all hosts in the cluster."""
    dictionary = PersonOverridesSnapshotDictionary(table)
    cluster.map_all_hosts(
        partial(
            dictionary.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
        )
    ).result()
    return dictionary


@dagster.op
def load_and_verify_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotDictionary:
    """Load the dictionary data on all hosts in the cluster, and ensure all hosts have identical data."""
    # Loading and verifying the dictionary can consume a lot of CPU and memory, so we limit the amount of parallel
    # queries to avoid substantial load increases on all hosts in the cluster at the same time, and instead try to
    # spread the load out more evenly and gracefully.
    checksums = cluster.map_all_hosts(dictionary.load, concurrency=1).result()
    assert len(set(checksums.values())) == 1
    return dictionary


# Mutation Management

ShardMutations = dict[int, Mutation]


@dagster.op
def start_person_id_update_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, ShardMutations]:
    """Start the mutation to update `sharded_events.person_id` with the snapshot data on all shards."""
    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(dictionary.person_id_update_mutation_runner.enqueue).result().items()
        )
    }
    return (dictionary, shard_mutations)


@dagster.op
def wait_for_person_id_update_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, ShardMutations],
) -> PersonOverridesSnapshotDictionary:
    """Wait for all hosts to complete the `sharded_events.person_id` update mutation."""
    [dictionary, shard_mutations] = inputs
    reduce(
        lambda x, y: x.merge(y),
        [cluster.map_all_hosts_in_shard(shard, mutation.wait) for shard, mutation in shard_mutations.items()],
    ).result()
    return dictionary


@dagster.op
def start_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, Mutation]:
    """Start the mutation to remove overrides contained within the snapshot from the overrides table."""
    mutation = cluster.any_host(dictionary.overrides_delete_mutation_runner.enqueue).result()
    return (dictionary, mutation)


@dagster.op
def wait_for_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, Mutation],
) -> PersonOverridesSnapshotDictionary:
    """Wait for all hosts to complete the mutation to remove overrides contained within the snapshot from the overrides table."""
    [dictionary, mutation] = inputs
    cluster.map_all_hosts(mutation.wait).result()
    return dictionary


# Cleanup


@dagster.op
def drop_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotTable:
    """Drop the snapshot dictionary on all hosts."""
    cluster.map_all_hosts(dictionary.drop).result()
    return dictionary.source


@dagster.op
def drop_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> None:
    """Drop the snapshot table on all hosts."""
    cluster.map_all_hosts(table.drop).result()


# Job Definition


@dagster.job
def squash_person_overrides():
    prepared_snapshot_table = wait_for_snapshot_table_replication(populate_snapshot_table(create_snapshot_table()))
    prepared_dictionary = load_and_verify_snapshot_dictionary(create_snapshot_dictionary(prepared_snapshot_table))
    dictionary_after_person_id_update_mutations = wait_for_person_id_update_mutations(
        start_person_id_update_mutations(prepared_dictionary)
    )
    dictionary_after_override_delete_mutations = wait_for_overrides_delete_mutations(
        start_overrides_delete_mutations(dictionary_after_person_id_update_mutations)
    )

    drop_snapshot_table(drop_snapshot_dictionary(dictionary_after_override_delete_mutations))
