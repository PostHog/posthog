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

    def is_loaded(self, client: Client) -> bool:
        results = client.execute(
            f"""
            SELECT status
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
            [[status]] = results
            return status == "LOADED"

    def reload(self, client: Client) -> None:
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")

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


class SnapshotConfig(dagster.Config):
    timestamp: int

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)


@dagster.op
def create_snapshot_table(context: dagster.OpExecutionContext, config: SnapshotConfig) -> PersonOverridesSnapshotTable:
    cluster = get_cluster()

    table = PersonOverridesSnapshotTable(
        id=uuid.UUID(context.run.run_id).hex,
        timestamp=config.datetime,
    )

    cluster.map_all_hosts(table.create).result()

    # TODO: wait for all hosts

    cluster.any_host(table.populate).result()

    return table


@dagster.op
def create_snapshot_dictionary(table: PersonOverridesSnapshotTable) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()

    dictionary = PersonOverridesSnapshotDictionary(table)

    cluster.map_all_hosts(dictionary.create).result()

    # TODO: wait for table to be available on all hosts

    cluster.map_all_hosts(dictionary.reload).result()

    # TODO: abstract this
    while True:  # todo: give up after a while
        waiting_on_hosts = {
            host for host, ready in cluster.map_all_hosts(dictionary.is_loaded).result().items() if not ready
        }
        if not waiting_on_hosts:
            break

        # TODO: logging, etc
        time.sleep(5)

    assert len(set(cluster.map_all_hosts(dictionary.get_checksum).result().values())) == 1

    return dictionary


@dagster.op
def run_person_id_update_mutation(dictionary: PersonOverridesSnapshotDictionary) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()

    cluster.map_one_host_per_shard(dictionary.enqueue_person_id_update_mutation).result()
    # TODO: need a way to target queries at all nodes on a shard to implement waiting correctly

    return dictionary


@dagster.op
def run_overrides_delete_mutation(dictionary: PersonOverridesSnapshotDictionary) -> PersonOverridesSnapshotDictionary:
    cluster = get_cluster()

    cluster.any_host(dictionary.enqueue_overrides_delete_mutation).result()
    # TODO: actually wait for the mutation to complete on all hosts

    return dictionary


@dagster.op
def drop_snapshot_dictionary(dictionary: PersonOverridesSnapshotDictionary) -> PersonOverridesSnapshotTable:
    cluster = get_cluster()

    cluster.map_all_hosts(dictionary.drop).result()
    # TODO: wait until it's done everywhere

    return dictionary.source


@dagster.op
def drop_snapshot_table(table: PersonOverridesSnapshotTable) -> None:
    cluster = get_cluster()

    cluster.map_all_hosts(table.drop).result()
    # TODO: wait until it's done everywhere


@dagster.job
def squash_person_overrides():
    drop_snapshot_table(
        drop_snapshot_dictionary(
            run_overrides_delete_mutation(
                run_person_id_update_mutation(create_snapshot_dictionary(create_snapshot_table()))
            )
        )
    )
