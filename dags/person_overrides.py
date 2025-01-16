from dataclasses import dataclass
from datetime import datetime

from clickhouse_driver import Client

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
        raise NotImplementedError


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
                AND name = %(name)
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
        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()}
            UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id))
            WHERE dictHas(%(name)s, (team_id, distinct_id))
            """,
            {"name": self.qualified_name},
        )
        raise NotImplementedError

    def enqueue_overrides_delete_mutation(self, client: Client) -> Mutation:
        client.execute(
            f"""
            ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_ID_OVERRIDES_TABLE}
            DELETE WHERE
                isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version)
                AND snapshot_version >= version
            """,
            {"name": self.qualified_name},
        )
        raise NotImplementedError
