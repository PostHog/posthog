import uuid
import datetime
from dataclasses import dataclass
from functools import partial

import dagster
import pydantic
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster, MutationWaiter
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE

from dags.common import JobOwners
from dags.common.overrides_manager import OverridesSnapshotDictionary, OverridesSnapshotTable


@dataclass
class PersonOverridesSnapshotTable(OverridesSnapshotTable):
    id: uuid.UUID

    @property
    def name(self) -> str:
        return f"person_distinct_id_overrides_snapshot_{self.id.hex}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (team_id Int64, distinct_id String, person_id UUID, version Int64)
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.qualified_name}', '{{replica}}-{{shard}}', version)
            ORDER BY (team_id, distinct_id)
            """
        )

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


@dataclass
class PersonOverridesSnapshotDictionary(OverridesSnapshotDictionary):
    source: PersonOverridesSnapshotTable

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
            SOURCE(CLICKHOUSE(DB %(database)s TABLE %(table)s USER %(user)s PASSWORD %(password)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": self.source.name,
                "user": settings.CLICKHOUSE_USER,
                "password": settings.CLICKHOUSE_PASSWORD,
            },
        )

    def get_checksum(self, client: Client):
        results = client.execute(
            f"""
             SELECT groupBitXor(row_checksum) AS table_checksum
             FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, distinct_id)
             """
        )
        [[checksum]] = results
        return checksum

    @property
    def update_table(self):
        return EVENTS_DATA_TABLE()

    @property
    def update_commands(self):
        return {
            "UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id)) WHERE dictHas(%(name)s, (team_id, distinct_id))"
        }

    @property
    def overrides_table(self):
        return PERSON_DISTINCT_ID_OVERRIDES_TABLE

    @property
    def overrides_deletes_predicate(self):
        return "isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version) AND snapshot_version >= version"


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
        "written to the database and replicated to all hosts in the cluster.",
        default=(datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    limit: int | None = pydantic.Field(
        description="The number of rows to include in the snapshot. If provided, this can be used to limit the total "
        "amount of memory consumed by the squash process during execution.",
        default=None,
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


class GetExistingDictionaryConfig(dagster.Config):
    id: str = pydantic.Field(description="The run ID of the original run that created the dictionary.")


@dagster.op
def get_existing_dictionary_for_run_id(
    config: GetExistingDictionaryConfig,
) -> PersonOverridesSnapshotDictionary:
    """
    Provides a handle to a snapshot dictionary based on the original run ID.

    This does not create the dictionary or ensure that it or any of its dependencies exist.
    """
    table = PersonOverridesSnapshotTable(uuid.UUID(config.id))
    return PersonOverridesSnapshotDictionary(table)


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


@dagster.op
def run_person_id_update_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotDictionary:
    dictionary.update_mutation_runner.run_on_shards(cluster)
    return dictionary


@dagster.op
def start_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, MutationWaiter]:
    """Start the mutation to remove overrides contained within the snapshot from the overrides table."""
    mutation = cluster.any_host(dictionary.overrides_delete_mutation_runner).result()
    return (dictionary, mutation)


@dagster.op
def wait_for_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, MutationWaiter],
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


def cleanup_snapshot_resources(dictionary: PersonOverridesSnapshotDictionary) -> None:
    return drop_snapshot_table(drop_snapshot_dictionary(dictionary))


# Job Definition


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def squash_person_overrides():
    prepared_snapshot_table = wait_for_snapshot_table_replication(populate_snapshot_table(create_snapshot_table()))
    prepared_dictionary = load_and_verify_snapshot_dictionary(create_snapshot_dictionary(prepared_snapshot_table))
    dictionary_after_person_id_update_mutations = run_person_id_update_mutations(prepared_dictionary)
    dictionary_after_override_delete_mutations = wait_for_overrides_delete_mutations(
        start_overrides_delete_mutations(dictionary_after_person_id_update_mutations)
    )
    cleanup_snapshot_resources(dictionary_after_override_delete_mutations)


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def cleanup_orphaned_person_overrides_snapshot():
    """
    Cleans up overrides snapshot resources after an irrecoverable job failure. This should only be run manually when the
    resources are guaranteed to no longer be in use (i.e. no mutations are in progress, and the specified job is no
    longer running and will not be retried.)

    Typically, these resources are automatically cleaned up after the job successfully completes. However, there are
    cases in which the job can fail and leave orphaned resources dangling around that can no longer be used and need to
    be manually removed from the cluster. This job can be used to perform the cleanup of those resources.
    """
    dictionary = get_existing_dictionary_for_run_id()
    cleanup_snapshot_resources(dictionary)


squash_schedule = dagster.ScheduleDefinition(
    job=squash_person_overrides,
    cron_schedule=settings.SQUASH_PERSON_OVERRIDES_SCHEDULE,
    execution_timezone="UTC",
    name="squash_person_overrides_schedule",
)
