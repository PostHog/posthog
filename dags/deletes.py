import pydantic
import time
from clickhouse_driver.client import Client
from datetime import datetime
from dataclasses import dataclass
from dagster import (
    asset,
    AssetExecutionContext,
    Config,
    MetadataValue,
    InitResourceContext,
    ResourceParam,
    ConfigurableResource,
)
from django.conf import settings
from functools import reduce

from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.async_deletion import AsyncDeletion, DeletionType


class ClickhouseClusterResource(ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "receive_timeout": f"{10 * 60}",
    }

    def create_resource(self, context: InitResourceContext) -> ClickhouseCluster:
        return get_cluster(context.log, client_settings=self.client_settings)


class DeleteConfig(Config):
    team_id: int | None = pydantic.Field(
        description="The team ID to delete events for. If not provided, all teams will be deleted :fire:"
    )


@dataclass
class Mutation:
    table: str
    mutation_id: str

    def is_done(self, client: Client) -> bool:
        result = client.execute(
            f"""
            SELECT is_done
            FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND mutation_id = %(mutation_id)s
            ORDER BY create_time DESC
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": self.table, "mutation_id": self.mutation_id},
        )
        return bool(result[0][0]) if result else False

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(15.0)


ShardMutations = dict[int, Mutation]


@dataclass
class PendingPersonEventDeletesTable:
    """
    Represents a temporary table storing pending person event deletions.
    """

    run_id: str
    cluster: str = settings.CLICKHOUSE_CLUSTER

    @property
    def table_name(self) -> str:
        return f"pending_person_deletes_{self.run_id}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    @property
    def dictionary_name(self) -> str:
        return f"{self.table_name}_dict"

    @property
    def create_table_query(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} ON CLUSTER '{self.cluster}'
            (
                team_id Int64,
                person_id UUID,
                created_at DateTime DEFAULT now()
            )
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.table_name}', '{{shard}}-{{replica}}')
            ORDER BY (team_id, person_id)
        """

    def drop_table_query(self) -> str:
        return f"DROP TABLE IF EXISTS {self.table_name} ON CLUSTER '{self.cluster}'"

    def drop_dictionary_query(self) -> str:
        return f"DROP DICTIONARY IF EXISTS {self.dictionary_name} ON CLUSTER '{self.cluster}'"

    def create(self, client: Client) -> None:
        client.execute(self.create_table_query)

    def drop(self, client: Client) -> None:
        client.execute(self.drop_table_query)

    def exists(self, client: Client) -> bool:
        result = client.execute(
            f"SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(table_name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table_name": self.table_name},
        )
        return bool(result[0][0]) if result else False

    @property
    def populate_query(self) -> str:
        return f"""
            INSERT INTO {self.table_name} (team_id, person_id, created_at)
            VALUES
        """


@dataclass
class PersonEventDeletesDictionary:
    source: PendingPersonEventDeletesTable

    @property
    def name(self) -> str:
        return f"{self.source.table_name}_dict"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    def create_statement(self, shards: int, max_execution_time: int) -> str:
        return f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
            (
                team_id Int64,
                person_id UUID,
                created_at DateTime
            )
            PRIMARY KEY team_id, person_id
            SOURCE(CLICKHOUSE(
                DB {settings.CLICKHOUSE_DATABASE}
                TABLE %(table)s
                PASSWORD %(password)s
            ))
            LIFETIME(0)
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            SETTINGS(max_execution_time={max_execution_time})
            """

    def exists(self, client: Client) -> bool:
        results = client.execute(
            "SELECT count() FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        [[count]] = results
        return count > 0

    def drop(self, client: Client) -> None:
        client.execute(
            f"DROP DICTIONARY IF EXISTS {self.qualified_name} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
        )

    def __is_loaded(self, client: Client) -> bool:
        result = client.execute(
            "SELECT status, last_exception FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        if not result:
            raise Exception("dictionary does not exist")

        status, last_exception = result[0]
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

    def __find_existing_mutation(self, client: Client, table: str, command_kind: str) -> Mutation | None:
        results = client.execute(
            f"""
            SELECT mutation_id
            FROM system.mutations
            WHERE
                database = %(database)s
                AND table = %(table)s
                AND startsWith(command, %(command_kind)s)
                AND command like concat('%%', %(name)s, '%%')
                AND NOT is_killed  -- ok to restart a killed mutation
            ORDER BY create_time DESC
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": table,
                "command_kind": command_kind,
                "name": self.qualified_name,
            },
        )
        if not results:
            return None
        else:
            assert len(results) == 1
            [[mutation_id]] = results
            return Mutation(table, mutation_id)

    def enqueue_person_event_delete_mutation(self, client: Client) -> Mutation:
        table = EVENTS_DATA_TABLE()

        # if this mutation already exists, don't start it again
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        if mutation := self.__find_existing_mutation(client, table, "UPDATE"):
            return mutation

        client.execute(
            # TODO: update to use created_at as limit
            f"""
            DELETE WHERE (team_id, person_id) IN (
                SELECT team_id, person_id
                FROM {self.qualified_name}
            )
            """
        )

        mutation = self.__find_existing_mutation(client, table, "UPDATE")
        assert mutation is not None
        return mutation


@asset
def create_pending_deletes_table(
    context: AssetExecutionContext,
    cluster: ResourceParam[ClickhouseCluster],
) -> PendingPersonEventDeletesTable:
    """Create a merge tree table in ClickHouse to store pending deletes."""
    table = PendingPersonEventDeletesTable(run_id=context.run_id, cluster=settings.CLICKHOUSE_CLUSTER)
    cluster.any_host(table.create).result()
    return table


@asset(deps=[create_pending_deletes_table])
def load_pending_person_deletions(
    context: AssetExecutionContext, config: DeleteConfig, create_pending_deletes_table: PendingPersonEventDeletesTable
) -> PendingPersonEventDeletesTable:
    """Query postgres using django ORM to get pending person deletions and insert directly into ClickHouse."""

    if not config.team_id:
        # Use Django's queryset iterator for memory efficiency
        pending_deletions = (
            AsyncDeletion.objects.filter(deletion_type=DeletionType.Person, delete_verified_at__isnull=True)
            .values("team_id", "key", "created_at")
            .iterator()
        )
    else:
        pending_deletions = (
            AsyncDeletion.objects.filter(
                deletion_type=DeletionType.Person,
                team_id=config.team_id,
                delete_verified_at__isnull=True,
            )
            .values("team_id", "key", "created_at")
            .iterator()
        )

    # Process and insert in chunks
    chunk_size = 10000
    current_chunk = []
    total_rows = 0

    client = Client(
        host=settings.CLICKHOUSE_HOST,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
    )

    for deletion in pending_deletions:
        # Rename 'key' to 'person_id' to match our schema
        current_chunk.append(
            {"team_id": deletion["team_id"], "person_id": deletion["key"], "created_at": deletion["created_at"]}
        )

        if len(current_chunk) >= chunk_size:
            client.execute(
                f"""
                INSERT INTO {create_pending_deletes_table.table_name} (team_id, person_id, created_at)
                VALUES
                """,
                current_chunk,
            )
            total_rows += len(current_chunk)
            current_chunk = []

    # Insert any remaining records
    if current_chunk:
        client.execute(
            f"""
            INSERT INTO {create_pending_deletes_table.table_name} (team_id, person_id, created_at)
            VALUES
            """,
            current_chunk,
        )
        total_rows += len(current_chunk)

    context.add_output_metadata(
        {
            "total_rows": MetadataValue.int(total_rows),
            "table_name": MetadataValue.text(create_pending_deletes_table.table_name),
        }
    )
    return create_pending_deletes_table


@asset(deps=[load_pending_person_deletions])
def create_pending_deletes_dictionary(
    cluster: ResourceParam[ClickhouseCluster], load_pending_person_deletions: PendingPersonEventDeletesTable
) -> PersonEventDeletesDictionary:
    """Create a dictionary table that wraps pending_person_deletes for efficient lookups."""
    delete_dictionary = PersonEventDeletesDictionary(source=load_pending_person_deletions)

    # Wait for the table to be fully replicated
    def sync_replica(client: Client):
        client.execute(f"SYSTEM SYNC REPLICA {load_pending_person_deletions.table_name} STRICT")

    cluster.map_all_hosts(sync_replica).result()

    # Create the dictionary using the table object
    def create_dict(client: Client):
        client.execute(delete_dictionary.create_statement(shards=1, max_execution_time=3600))

    cluster.any_host(create_dict).result()
    return delete_dictionary


@asset(deps=[create_pending_deletes_dictionary])
def delete_person_events(
    context: AssetExecutionContext,
    cluster: ResourceParam[ClickhouseCluster],
    create_pending_deletes_dictionary: PersonEventDeletesDictionary,
) -> tuple[PersonEventDeletesDictionary, ShardMutations]:
    """Delete events from sharded_events table for persons pending deletion."""

    def count_pending_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count()
            FROM {create_pending_deletes_dictionary.dictionary_name}
            """
        )
        return result[0][0] if result else 0

    count_result = cluster.any_host(count_pending_deletes).result()

    if count_result == 0:
        context.add_output_metadata({"events_deleted": MetadataValue.int(0), "message": "No pending deletions found"})
        return (create_pending_deletes_dictionary, {})

    context.add_output_metadata(
        {
            "events_deleted": MetadataValue.int(count_result),
        }
    )

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(create_pending_deletes_dictionary.enqueue_person_event_delete_mutation)
            .result()
            .items()
        )
    }
    return (create_pending_deletes_dictionary, shard_mutations)


@asset(deps=[delete_person_events])
def wait_for_delete_mutations(
    cluster: ResourceParam[ClickhouseCluster],
    delete_person_events: tuple[PersonEventDeletesDictionary, ShardMutations],
) -> PersonEventDeletesDictionary:
    dictionary, shard_mutations = delete_person_events
    reduce(
        lambda x, y: x.merge(y),
        [cluster.map_all_hosts_in_shard(shard, mutation.wait) for shard, mutation in shard_mutations.items()],
    ).result()
    return dictionary


@asset(deps=[delete_person_events])
def cleanup_delete_assets(
    cluster: ResourceParam[ClickhouseCluster],
    config: DeleteConfig,
    create_pending_deletes_table: PendingPersonEventDeletesTable,
    wait_for_delete_mutations: PersonEventDeletesDictionary,
) -> bool:
    """Clean up temporary tables, dictionary, and mark deletions as verified."""
    # Drop the dictionary and table using the table object

    cluster.any_host(create_pending_deletes_table.drop).result()
    cluster.any_host(wait_for_delete_mutations.drop).result()

    # Mark deletions as verified in Django
    if not config.team_id:
        AsyncDeletion.objects.filter(deletion_type=DeletionType.Person, delete_verified_at__isnull=True).update(
            delete_verified_at=datetime.now()
        )
    else:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person, team_id=config.team_id, delete_verified_at__isnull=True
        ).update(delete_verified_at=datetime.now())

    return True
