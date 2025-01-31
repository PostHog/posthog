import pydantic
from clickhouse_driver.client import Client
from datetime import datetime
from dataclasses import dataclass
from dagster import (
    op,
    job,
    OpExecutionContext,
    Config,
    MetadataValue,
    InitResourceContext,
    ResourceParam,
    ConfigurableResource,
)
from django.conf import settings

from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    Mutation,
    MutationRunner,
    NodeRole,
    get_cluster,
)
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
        default=None, description="The team ID to delete events for. If not provided, all teams will be deleted :fire:"
    )
    timestamp: str = pydantic.Field(
        default=datetime.now().isoformat(),
        description="The timestamp to delete events up to in ISO format (YYYY-MM-DDTHH:MM:SS.mmmmmm+HH:MM). If not provided, current time will be used.",
    )
    cleanup: bool = pydantic.Field(
        default=True,
        description="If true, the temporary table will be dropped after the job is run.",
    )

    @property
    def parsed_timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


ShardMutations = dict[int, Mutation]


@dataclass
class PendingPersonEventDeletesTable:
    """
    Represents a temporary table storing pending person event deletions.
    """

    timestamp: datetime
    team_id: int | None = None
    cluster: str = settings.CLICKHOUSE_CLUSTER

    @property
    def timestamp_isoformat(self) -> str:
        return self.timestamp.isoformat()

    @property
    def clickhouse_timestamp(self) -> str:
        return self.timestamp.strftime("%Y%m%d_%H%M%S")

    @property
    def table_name(self) -> str:
        return f"pending_person_deletes_{self.clickhouse_timestamp}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    @property
    def create_table_query(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'
            (
                team_id Int64,
                deletion_type Int8,
                key String,
                created_at DateTime,
                delete_verified_at Nullable(DateTime)
            )
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.table_name}', '{{shard}}-{{replica}}')
            ORDER BY (team_id, deletion_type, key)
        """

    @property
    def drop_table_query(self) -> str:
        return f"DROP TABLE IF EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'"

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
            INSERT INTO {self.qualified_name} (team_id, deletion_type, key, created_at)
            VALUES
        """

    def checksum(self, client: Client):
        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, deletion_type, key, created_at)
            """
        )
        [[checksum]] = results
        return checksum


@dataclass
class PendingEventDeletesTable:
    """
    Represents a temporary table storing pending event deletions.
    """

    timestamp: datetime
    team_id: int | None = None
    cluster: str = settings.CLICKHOUSE_CLUSTER
    pending_person_deletions_qualified_name: str = ""

    @property
    def timestamp_isoformat(self) -> str:
        return self.timestamp.isoformat()

    @property
    def clickhouse_timestamp(self) -> str:
        return self.timestamp.strftime("%Y%m%d_%H%M%S")

    @property
    def table_name(self) -> str:
        return f"pending_event_deletes_{self.clickhouse_timestamp}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    @property
    def create_table_query(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'
            (
                uuid UUID,
                event String,
                team_id Int64,
                person_id UUID,
                timestamp DateTime
            )
            ENGINE = ReplacingMergeTree()
            ORDER BY (team_id, event, person_id, timestamp)
        """

    @property
    def drop_table_query(self) -> str:
        return f"DROP TABLE IF EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'"

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
            INSERT INTO {self.qualified_name} (uuid, event, team_id, person_id, timestamp)
            SELECT e.uuid, e.event, e.team_id, e.person_id, e.timestamp
                FROM {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()} e
                INNER JOIN {self.pending_person_deletions_qualified_name} d
                ON e.team_id = d.team_id
                AND toString(e.person_id) = d.key
                WHERE
                    e.timestamp < d.created_at
                    AND d.delete_verified_at IS NULL
                    AND d.deletion_type = 1
        """

    @property
    def person_event_delete_mutation_runner(self) -> MutationRunner:
        return MutationRunner(
            EVENTS_DATA_TABLE(),
            f"""
            DELETE FROM {EVENTS_DATA_TABLE()} WHERE (uuid, event, team_id, person_id, timestamp) IN (
                SELECT uuid, event, team_id, person_id, timestamp
                FROM {self.qualified_name}
            )
            """,
            {},
        )

    def checksum(self, client: Client):
        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, deletion_type, key, created_at)
            """
        )
        [[checksum]] = results
        return checksum


@op
def create_pending_person_deletions_table(
    config: DeleteConfig,
    cluster: ResourceParam[ClickhouseCluster],
) -> PendingPersonEventDeletesTable:
    """Create a merge tree table in ClickHouse to store pending deletes."""
    table = PendingPersonEventDeletesTable(
        timestamp=config.parsed_timestamp,
        team_id=config.team_id,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
    cluster.any_host(table.create).result()
    return table


@op
def load_pending_person_deletions(
    context: OpExecutionContext,
    create_pending_person_deletions_table: PendingPersonEventDeletesTable,
) -> PendingPersonEventDeletesTable:
    """Query postgres using django ORM to get pending person deletions and insert directly into ClickHouse."""

    if not create_pending_person_deletions_table.team_id:
        # Use Django's queryset iterator for memory efficiency
        pending_deletions = AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).iterator()
    else:
        pending_deletions = AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            team_id=create_pending_person_deletions_table.team_id,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).iterator()

    # Process and insert in chunks
    chunk_size = 10000
    current_chunk = []
    total_rows = 0

    client = Client(
        host=settings.CLICKHOUSE_HOST,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
        verify=settings.CLICKHOUSE_VERIFY,
    )

    for deletion in pending_deletions:
        current_chunk.append(
            {
                "team_id": deletion.team_id,
                "deletion_type": deletion.deletion_type,
                "key": deletion.key,
                "created_at": deletion.created_at,
            }
        )

        if len(current_chunk) >= chunk_size:
            client.execute(
                create_pending_person_deletions_table.populate_query,
                current_chunk,
            )
            total_rows += len(current_chunk)
            current_chunk = []

    # Insert any remaining records
    if current_chunk:
        client.execute(
            create_pending_person_deletions_table.populate_query,
            current_chunk,
        )
        total_rows += len(current_chunk)

    context.add_output_metadata(
        {
            "total_rows": MetadataValue.int(total_rows),
            "table_name": MetadataValue.text(create_pending_person_deletions_table.table_name),
        }
    )
    return create_pending_person_deletions_table


@op
def create_pending_event_deletes_table(
    config: DeleteConfig,
    create_pending_person_deletions_table: PendingPersonEventDeletesTable,
    cluster: ResourceParam[ClickhouseCluster],
) -> PendingEventDeletesTable:
    """Create a merge tree table in ClickHouse to store pending event deletions."""
    table = PendingEventDeletesTable(
        timestamp=create_pending_person_deletions_table.timestamp,
        cluster=settings.CLICKHOUSE_CLUSTER,
        pending_person_deletions_qualified_name=create_pending_person_deletions_table.qualified_name,
    )

    cluster.any_host(table.create).result()
    return table


@op
def load_pending_event_deletes(
    context: OpExecutionContext,
    create_pending_event_deletes_table: PendingEventDeletesTable,
    load_pending_person_deletions: PendingPersonEventDeletesTable,
    cluster: ResourceParam[ClickhouseCluster],
) -> PendingEventDeletesTable:
    """Query postgres using django ORM to get pending event deletions and insert directly into ClickHouse."""

    # Wait for the table to be fully replicated
    def sync_replica(client: Client):
        client.execute(f"SYSTEM SYNC REPLICA {load_pending_person_deletions.qualified_name} STRICT")

    cluster.map_hosts_by_role(sync_replica, NodeRole.WORKER).result()

    # Load pending event deletions
    def load_pending_event_deletions(client: Client):
        client.execute(create_pending_event_deletes_table.populate_query)

    cluster.map_hosts_by_role(load_pending_event_deletions, NodeRole.WORKER).result()

    return create_pending_event_deletes_table


@op
def delete_person_events(
    context: OpExecutionContext,
    cluster: ResourceParam[ClickhouseCluster],
    load_pending_event_deletions: PendingEventDeletesTable,
) -> tuple[PendingEventDeletesTable, ShardMutations]:
    """Delete events from sharded_events table for persons pending deletion."""

    def count_pending_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count()
            FROM {load_pending_event_deletions.qualified_name}
            """
        )
        return result[0][0] if result else 0

    count_result = cluster.map_hosts_by_role(count_pending_deletes, NodeRole.WORKER).result()

    all_zero = all(count == 0 for count in count_result.values())
    if all_zero:
        context.add_output_metadata({"events_deleted": MetadataValue.int(0), "message": "No pending deletions found"})
        return (load_pending_event_deletions, {})

    context.add_output_metadata(
        {
            "events_deleted": MetadataValue.int(sum(count_result.values())),
        }
    )

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(load_pending_event_deletions.person_event_delete_mutation_runner.enqueue)
            .result()
            .items()
        )
    }
    return (load_pending_event_deletions, shard_mutations)


@op
def wait_for_delete_mutations(
    context: OpExecutionContext,
    cluster: ResourceParam[ClickhouseCluster],
    delete_person_events: tuple[PendingEventDeletesTable, ShardMutations],
) -> PendingEventDeletesTable:
    pending_event_deletions, shard_mutations = delete_person_events

    cluster.map_all_hosts_in_shards({shard: mutation.wait for shard, mutation in shard_mutations.items()}).result()

    return pending_event_deletions


@op
def cleanup_delete_assets(
    cluster: ResourceParam[ClickhouseCluster],
    config: DeleteConfig,
    create_pending_person_deletions_table: PendingPersonEventDeletesTable,
    create_pending_event_deletes_table: PendingEventDeletesTable,
    wait_for_delete_mutations: PendingEventDeletesTable,
) -> bool:
    """Clean up temporary tables and mark deletions as verified."""
    # Drop the dictionary and table using the table object

    if not config.cleanup:
        config.log.info("Skipping cleanup as cleanup is disabled")
        return True

    cluster.any_host_by_role(create_pending_person_deletions_table.drop, NodeRole.WORKER).result()
    cluster.any_host_by_role(create_pending_event_deletes_table.drop, NodeRole.WORKER).result()

    # Mark deletions as verified in Django
    if not create_pending_person_deletions_table.team_id:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).update(delete_verified_at=datetime.now())
    else:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            team_id=create_pending_person_deletions_table.team_id,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).update(delete_verified_at=datetime.now())

    return True


@job
def deletes_job():
    """Job that handles deletion of person events."""
    person_table = create_pending_person_deletions_table()
    event_table = create_pending_event_deletes_table(person_table)
    loaded_person_table = load_pending_person_deletions(person_table)
    loaded_event_table = load_pending_event_deletes(event_table, loaded_person_table)
    delete_events = delete_person_events(loaded_event_table)
    waited_table = wait_for_delete_mutations(delete_events)
    cleanup_delete_assets(person_table, event_table, waited_table)
