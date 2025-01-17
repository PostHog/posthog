import time
import uuid
from dataclasses import dataclass
from functools import partial, reduce

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from ee.clickhouse.materialized_columns.columns import get_cluster  # XXX
from posthog import settings
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE


class ClickhouseClusterResource(dagster.ConfigurableResource):
    client_settings: dict[str, str] | None = None

    def create_resource(self, context: dagster.InitResourceContext) -> ClickhouseCluster:
        return get_cluster(context.log, client_settings=self.client_settings)


@dataclass
class PersonOverridesSnapshotTable:
    id: str
    timestamp: str

    @property
    def name(self) -> str:
        return f"person_distinct_id_overrides_snapshot_{self.id}"

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
            f"SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} SYNC")

    def populate(self, client: Client) -> None:
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        # this could optionally support truncate as a config option if necessary to reset the table state, or
        # force an optimize after insertion to compact the table before dictionary insertion (if that's even needed)
        [[count]] = client.execute(f"SELECT count() FROM {self.qualified_name}")
        assert count == 0

        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (team_id, distinct_id, person_id, version)
            SELECT team_id, distinct_id, argMax(person_id, version), max(version)
            FROM {settings.CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_ID_OVERRIDES_TABLE}
            WHERE _timestamp < %(timestamp)s
            GROUP BY team_id, distinct_id
            """,
            {"timestamp": self.timestamp},
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
class Mutation:
    table: str
    mutation_id: str

    def is_done(self, client: Client) -> bool:
        [[is_done]] = client.execute(
            f"""
            SELECT is_done
            FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND mutation_id = %(mutation_id)s
            ORDER BY create_time DESC
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.table, "mutation_id": self.mutation_id},
        )
        return is_done

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(15.0)


@dataclass
class PersonOverridesSnapshotDictionary:
    source: PersonOverridesSnapshotTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client, shards: int, max_execution_time: int) -> None:
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
            SETTINGS(max_execution_time={max_execution_time})
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

    def enqueue_person_id_update_mutation(self, client: Client) -> Mutation:
        table = EVENTS_DATA_TABLE()

        def _find_existing_mutation() -> Mutation | None:
            results = client.execute(
                f"""
                SELECT mutation_id
                FROM system.mutations
                WHERE
                    database = %(database)s
                    AND table = %(table)s
                    AND startsWith(command, 'UPDATE')
                    AND command like concat('%%', %(name)s, '%%')
                    AND NOT is_killed  -- ok to restart a killed mutation
                ORDER BY create_time DESC
                """,
                {
                    "database": settings.CLICKHOUSE_DATABASE,
                    "table": table,
                    "name": self.qualified_name,
                },
            )
            if not results:
                return None
            else:
                assert len(results) == 1
                [[mutation_id]] = results
                return Mutation(table, mutation_id)

        # if this mutation already exists, don't start it again
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        if mutation := _find_existing_mutation():
            return mutation

        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table}
            UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id))
            WHERE dictHas(%(name)s, (team_id, distinct_id))
            """,
            {"name": self.qualified_name},
        )

        mutation = _find_existing_mutation()
        assert mutation is not None

        return mutation

    def enqueue_overrides_delete_mutation(self, client: Client) -> Mutation:
        table = PERSON_DISTINCT_ID_OVERRIDES_TABLE

        def _find_existing_mutation() -> Mutation | None:
            results = client.execute(
                f"""
                SELECT mutation_id
                FROM system.mutations
                WHERE
                    database = %(database)s
                    AND table = %(table)s
                    AND startsWith(command, 'DELETE')
                    AND command like concat('%%', %(name)s, '%%')
                    AND NOT is_killed  -- ok to restart a killed mutation
                ORDER BY create_time DESC
                """,
                {
                    "database": settings.CLICKHOUSE_DATABASE,
                    "table": table,
                    "name": self.qualified_name,
                },
            )
            if not results:
                return None
            else:
                assert len(results) == 1
                [[mutation_id]] = results
                return Mutation(table, mutation_id)

        # if this mutation already exists, don't start it again
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        if mutation := _find_existing_mutation():
            return mutation

        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table}
            DELETE WHERE
                isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version)
                AND snapshot_version >= version
            """,
            {"name": self.qualified_name},
        )

        mutation = _find_existing_mutation()
        assert mutation is not None

        return mutation


# Snapshot Table Management


class SnapshotTableConfig(dagster.Config):
    timestamp: str


@dagster.op
def create_snapshot_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: SnapshotTableConfig,
) -> PersonOverridesSnapshotTable:
    table = PersonOverridesSnapshotTable(
        id=uuid.UUID(context.run.run_id).hex,
        timestamp=config.timestamp,
    )
    cluster.map_all_hosts(table.create).result()
    return table


@dagster.op
def populate_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotTable:
    cluster.any_host(table.populate).result()
    return table


@dagster.op
def wait_for_snapshot_table_replication(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotTable:
    cluster.map_all_hosts(table.sync).result()
    return table


# Snapshot Dictionary Management


class SnapshotDictionaryConfig(dagster.Config):
    shards: int = 16
    max_execution_time: int = 15 * 60


@dagster.op
def create_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: SnapshotDictionaryConfig,
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotDictionary:
    dictionary = PersonOverridesSnapshotDictionary(table)
    cluster.map_all_hosts(
        partial(
            dictionary.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
        )
    ).result()
    return dictionary


@dagster.op
def load_and_verify_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotDictionary:
    checksums = cluster.map_all_hosts(dictionary.load).result()
    assert len(set(checksums.values())) == 1
    return dictionary


# Mutation Management

ShardMutations = dict[int, Mutation]


@dagster.op
def start_person_id_update_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, ShardMutations]:
    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(dictionary.enqueue_person_id_update_mutation).result().items()
        )
    }
    return (dictionary, shard_mutations)


@dagster.op
def wait_for_person_id_update_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, ShardMutations],
) -> PersonOverridesSnapshotDictionary:
    [dictionary, shard_mutations] = inputs
    reduce(
        lambda x, y: x | y,
        [cluster.map_all_hosts_in_shard(shard, mutation.wait) for shard, mutation in shard_mutations.items()],
    ).result()
    return dictionary


@dagster.op
def start_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, Mutation]:
    mutation = cluster.any_host(dictionary.enqueue_overrides_delete_mutation).result()
    return (dictionary, mutation)


@dagster.op
def wait_for_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, Mutation],
) -> PersonOverridesSnapshotDictionary:
    [dictionary, mutation] = inputs
    cluster.map_all_hosts(mutation.wait).result()
    return dictionary


@dagster.op
def drop_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotTable:
    cluster.map_all_hosts(dictionary.drop).result()
    return dictionary.source


@dagster.op
def drop_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> None:
    cluster.map_all_hosts(table.drop).result()


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
