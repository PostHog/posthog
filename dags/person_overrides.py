import time
from dataclasses import dataclass
from datetime import datetime
import uuid

import dagster
from clickhouse_driver import Client

from ee.clickhouse.materialized_columns.columns import get_cluster  # XXX
from posthog import settings
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE


@dataclass
class PersonOverridesSnapshotTable:
    id: str
    timestamp: datetime

    @property
    def name(self) -> str:
        return f"person_distinct_id_overrides_snapshot_{self.id}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE TABLE {self.qualified_name} (
                team_id Int64,
                distinct_id String,
                person_id UUID,
                version Int64
            )
            ENGINE = ReplicatedReplacingMergeTree(
                '/clickhouse/tables/noshard/{self.qualified_name}',
                '{{replica}}-{{shard}}',
                version
            )
            ORDER BY (team_id, distinct_id)
            """
        )

    def exists(self, client: Client) -> None:
        results = client.execute(
            f"""
                SELECT count()
                FROM system.tables
                WHERE
                    database = %(database)s
                    AND name = %(name)
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "name": self.name,
            },
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE {self.qualified_name} SYNC")

    def populate(self, client: Client) -> None:
        client.execute(
            f"""
            INSERT INTO {self.qualified_name}
                (team_id, distinct_id, person_id, version)
            SELECT
                team_id,
                distinct_id,
                argMax(person_id, version),
                max(version)
            FROM {settings.CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_ID_OVERRIDES_TABLE}
            WHERE _timestamp < %(timestamp)s
            GROUP BY team_id, distinct_id
            """,
            {"timestamp": self.timestamp},
        )

    def sync(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")

    def get_queue_size(self, client: Client) -> int:
        [[queue_size]] = client.execute(
            """
            SELECT queue_size
            FROM system.replicas
            WHERE
                database = %(database)s
                AND table = %(table)s
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.name},
        )
        return queue_size


@dataclass
class Mutation:
    table: str
    mutation_id: str

    def is_done(self, client: Client) -> bool:
        [[is_done]] = client.execute(
            f"""
            SELECT is_done
            FROM system.mutations
            WHERE
                database = %(database)s
                AND table = %(table)s
                AND mutation_id = %(mutation_id)s
            ORDER BY create_time DESC
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": self.table,
                "mutation_id": self.mutation_id,
            },
        )
        return is_done


@dataclass
class PersonOverridesSnapshotDictionary:
    source: PersonOverridesSnapshotTable

    @property
    def name(self) -> str:
        return f"{self.source.name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE DICTIONARY {self.qualified_name} (
                team_id Int64,
                distinct_id String,
                person_id UUID,
                version Int64
            )
            PRIMARY KEY team_id, distinct_id
            SOURCE(CLICKHOUSE(
                DB %(database)s
                TABLE %(table)s
                PASSWORD %(password)s
            ))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS 16))
            LIFETIME(0)
            SETTINGS(max_execution_time=900)
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": self.source.name,
                "password": settings.CLICKHOUSE_PASSWORD,
            },
        )

    def exists(self, client: Client) -> bool:
        results = client.execute(
            f"""
            SELECT count()
            FROM system.dictionaries
            WHERE
                database = %(database)s
                AND name = %(name)
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "name": self.name,
            },
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(f"DROP DICTIONARY {self.qualified_name} SYNC")

    def __is_loaded(self, client: Client) -> bool:
        results = client.execute(
            f"""
            SELECT status, last_exception
            FROM system.dictionaries
            WHERE
                database = %(database)s
                AND name = %(name)s
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "name": self.name,
            },
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

    def load(self, client: Client) -> None:
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")
        while not self.__is_loaded(client):
            time.sleep(5.0)

    def get_checksum(self, client: Client):  # TODO: check return type
        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (
                SELECT cityHash64(*) AS row_checksum
                FROM {self.qualified_name}
                ORDER BY team_id, distinct_id
            )
            """
        )
        [[checksum]] = results
        return checksum

    def enqueue_person_id_update_mutation(self, client: Client) -> Mutation:
        table = EVENTS_DATA_TABLE()
        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table}
            UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id))
            WHERE dictHas(%(name)s, (team_id, distinct_id))
            """,
            {"name": self.qualified_name},
        )

        [[table, mutation_id]] = client.execute(
            f"""
            SELECT table, mutation_id
            FROM system.mutations
            WHERE
                database = %(database)s
                AND table = %(table)s
                AND startsWith(command, 'UPDATE')
                AND command like concat('%%', %(name)s, '%%')
            ORDER BY create_time DESC
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": table,
                "name": self.qualified_name,
            },
        )

        return Mutation(table, mutation_id)

    def enqueue_overrides_delete_mutation(self, client: Client) -> Mutation:
        table = PERSON_DISTINCT_ID_OVERRIDES_TABLE
        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table}
            DELETE WHERE
                isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version)
                AND snapshot_version >= version
            """,
            {"name": self.qualified_name},
        )

        [[table, mutation_id]] = client.execute(
            f"""
            SELECT table, mutation_id
            FROM system.mutations
            WHERE
                database = %(database)s
                AND table = %(table)s
                AND startsWith(command, 'DELETE')
                AND command like concat('%%', %(name)s, '%%')
            ORDER BY create_time DESC
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": table,
                "name": self.qualified_name,
            },
        )

        return Mutation(table, mutation_id)


# Snapshot Table Management


class SnapshotConfig(dagster.Config):
    timestamp: int

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)


@dagster.op
def create_snapshot_table(context: dagster.OpExecutionContext, config: SnapshotConfig) -> PersonOverridesSnapshotTable:
    table = PersonOverridesSnapshotTable(
        id=uuid.UUID(context.run.run_id).hex,
        timestamp=config.datetime,
    )
    get_cluster().map_all_hosts(table.create).result()
    return table


@dagster.op
def populate_snapshot_table(table: PersonOverridesSnapshotTable) -> PersonOverridesSnapshotTable:
    get_cluster().any_host(table.populate).result()
    return table


@dagster.op
def wait_for_snapshot_table_replication(table: PersonOverridesSnapshotTable) -> PersonOverridesSnapshotTable:
    cluster = get_cluster()
    cluster.map_all_hosts(table.sync).result()

    hosts_with_nonempty_queues = {
        host for host, queue_size in cluster.map_all_hosts(table.get_queue_size).result().items() if queue_size > 0
    }
    assert not hosts_with_nonempty_queues

    return table


# Snapshot Dictionary Management


@dagster.op
def create_snapshot_dictionary(table: PersonOverridesSnapshotTable) -> PersonOverridesSnapshotDictionary:
    dictionary = PersonOverridesSnapshotDictionary(table)
    get_cluster().map_all_hosts(dictionary.create).result()
    return dictionary


@dagster.op
def load_snapshot_dictionary(dictionary: PersonOverridesSnapshotDictionary) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()
    cluster.map_all_hosts(dictionary.load).result()
    assert len(set(cluster.map_all_hosts(dictionary.get_checksum).result().values())) == 1
    return dictionary


# Mutation Management


@dagster.op
def run_person_id_update_mutation(
    context: dagster.OpExecutionContext, dictionary: PersonOverridesSnapshotDictionary
) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(dictionary.enqueue_person_id_update_mutation).result().items()
        )
    }

    while True:
        waiting_on_hosts = set()

        # TODO: mutation may not have been replicated yet
        shard_mutation_statuses = {
            shard: cluster.map_all_hosts_in_shard(shard, mutation.is_done)
            for shard, mutation in shard_mutations.items()
        }
        for host_mutation_statuses in shard_mutation_statuses.values():
            waiting_on_hosts.update(host for host, is_done in host_mutation_statuses.result().items() if not is_done)

        if waiting_on_hosts:
            context.log.info("Still waiting on %r to finish mutation...", waiting_on_hosts)
            time.sleep(15.0)
        else:
            break

    return dictionary


@dagster.op
def run_overrides_delete_mutation(
    context: dagster.OpExecutionContext, dictionary: PersonOverridesSnapshotDictionary
) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()

    mutation = cluster.any_host(dictionary.enqueue_overrides_delete_mutation).result()

    while True:
        # TODO: mutation may not have been replicated yet
        waiting_on_hosts = {host for host, is_done in cluster.map_all_hosts(mutation.is_done) if not is_done}
        if waiting_on_hosts:
            context.log.info("Still waiting on %r to finish mutation...", waiting_on_hosts)
            time.sleep(15.0)
        else:
            break

    return dictionary


@dagster.op
def drop_snapshot_dictionary(dictionary: PersonOverridesSnapshotDictionary) -> PersonOverridesSnapshotTable:
    get_cluster().map_all_hosts(dictionary.drop).result()
    return dictionary.source


@dagster.op
def drop_snapshot_table(table: PersonOverridesSnapshotTable) -> None:
    get_cluster().map_all_hosts(table.drop).result()


@dagster.job
def squash_person_overrides():
    prepared_snapshot_table = wait_for_snapshot_table_replication(populate_snapshot_table(create_snapshot_table()))
    prepared_dictionary = load_snapshot_dictionary(create_snapshot_dictionary(prepared_snapshot_table))

    drop_snapshot_table(
        drop_snapshot_dictionary(run_overrides_delete_mutation(run_person_id_update_mutation(prepared_dictionary)))
    )
