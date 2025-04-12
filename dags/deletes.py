import pydantic
import time
from clickhouse_driver.client import Client
from datetime import datetime
from dataclasses import dataclass
import dagster
from django.conf import settings
from functools import partial
import uuid
from django.utils import timezone

from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    MutationWaiter,
    LightweightDeleteMutationRunner,
    NodeRole,
    Query,
)
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE

from dags.common import JobOwners
from dags.person_overrides import squash_person_overrides


class DeleteConfig(dagster.Config):
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
    shards: int = pydantic.Field(
        default=16,
        description="The number of shards to be used when building the dictionary. Using larger values can speed up the "
        "creation process. See the ClickHouse documentation for more information.",
    )
    max_execution_time: int = pydantic.Field(
        default=0,
        description="The maximum amount of time to wait for the dictionary load to complete before considering the operation "
        "a failure, or 0 to wait an unlimited amount of time.",
    )
    max_memory_usage: int = pydantic.Field(
        default=0,
        description="The maximum amount of memory to use for the dictionary, or 0 to use an unlimited amount.",
    )

    @property
    def parsed_timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


ShardMutations = dict[int, MutationWaiter]


@dataclass
class PendingPersonEventDeletesTable:
    """
    Represents a table storing pending person event deletions.
    """

    timestamp: datetime
    team_id: int | None = None
    cluster: str = settings.CLICKHOUSE_CLUSTER
    is_reporting: bool = False

    @property
    def timestamp_isoformat(self) -> str:
        return self.timestamp.isoformat()

    @property
    def clickhouse_timestamp(self) -> str:
        return self.timestamp.strftime("%Y%m%d_%H%M%S")

    @property
    def table_name(self) -> str:
        if self.is_reporting:
            return "pending_person_deletes_reporting"
        else:
            return f"pending_person_deletes_{self.clickhouse_timestamp}"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    @property
    def zk_path(self) -> str:
        ns_uuid = uuid.uuid4()
        testing = f"testing/{ns_uuid}/" if settings.TEST else ""
        return f"/clickhouse/tables/{testing}noshard/{self.table_name}"

    @property
    def create_table_query(self) -> str:
        return f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'
            (
                id UInt64,
                deletion_type UInt8,
                key String,
                group_type_index Nullable(String),
                created_at DateTime,
                delete_verified_at Nullable(DateTime),
                created_by_id Nullable(String),
                team_id Int64
            )
            ENGINE = ReplicatedReplacingMergeTree('{self.zk_path}', '{{shard}}-{{replica}}')
            ORDER BY (team_id, deletion_type, key)
        """

    @property
    def truncate_table_query(self) -> str:
        return f"TRUNCATE TABLE {self.qualified_name} ON CLUSTER '{self.cluster}'"

    @property
    def drop_table_query(self) -> str:
        return f"DROP TABLE IF EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'"

    def create(self, client: Client) -> None:
        client.execute(self.create_table_query)

    def truncate(self, client: Client) -> None:
        client.execute(self.truncate_table_query)

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
            INSERT INTO {self.qualified_name} (
                id,
                deletion_type,
                key,
                group_type_index,
                created_at,
                delete_verified_at,
                created_by_id,
                team_id
            )
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
class PendingDeletesDictionary:
    source: PendingPersonEventDeletesTable

    @property
    def name(self) -> str:
        return f"{self.source.table_name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    @property
    def query(self) -> str:
        return f"SELECT team_id, key, created_at FROM {self.source.qualified_name} WHERE deletion_type = 1"

    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' (
                team_id Int64,
                key String,
                created_at DateTime,
            )
            PRIMARY KEY team_id, key
            SOURCE(CLICKHOUSE(DB %(database)s USER %(user)s PASSWORD %(password)s QUERY %(query)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "user": settings.CLICKHOUSE_USER,
                "password": settings.CLICKHOUSE_PASSWORD,
                "query": self.query,
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
        client.execute(
            f"DROP DICTIONARY IF EXISTS {self.qualified_name} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
        )

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
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, key)
            """
        )
        [[checksum]] = results
        return checksum

    @property
    def delete_mutation_runner(self) -> LightweightDeleteMutationRunner:
        return LightweightDeleteMutationRunner(
            EVENTS_DATA_TABLE(),
            "dictHas(%(dictionary)s, (team_id, person_id)) AND timestamp <= dictGet(%(dictionary)s, 'created_at', (team_id, person_id))",
            parameters={"dictionary": self.qualified_name},
        )


@dagster.op
def get_oldest_person_override_timestamp(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> datetime:
    """Get the oldest person override timestamp from the person_distinct_id_overrides table."""

    query = f"""
    SELECT min(_timestamp) FROM {PERSON_DISTINCT_ID_OVERRIDES_TABLE}
    """
    [[result]] = cluster.any_host_by_role(lambda client: client.execute(query), NodeRole.DATA).result()
    return result


@dagster.op
def create_pending_person_deletions_table(
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    oldest_person_override_timestamp: datetime,
) -> PendingPersonEventDeletesTable:
    """
    Create a merge tree table in ClickHouse to store pending deletes.

    Important to note: we only get pending deletions for requests that happened before the oldest person override timestamp.
    """

    table = PendingPersonEventDeletesTable(
        timestamp=oldest_person_override_timestamp,
        team_id=config.team_id,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
    cluster.any_host_by_role(table.create, NodeRole.DATA).result()
    return table


@dagster.op
def create_reporting_pending_person_deletions_table(
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingPersonEventDeletesTable:
    """Create a merge tree table in ClickHouse to store pending deletes."""
    table = PendingPersonEventDeletesTable(
        timestamp=config.parsed_timestamp,
        cluster=settings.CLICKHOUSE_CLUSTER,
        is_reporting=True,
    )
    cluster.any_host_by_role(table.create, NodeRole.DATA).result()
    cluster.any_host_by_role(table.truncate, NodeRole.DATA).result()
    return table


@dagster.op
def load_pending_person_deletions(
    context: dagster.OpExecutionContext,
    create_pending_person_deletions_table: PendingPersonEventDeletesTable,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    cleanup_delete_assets: bool | None = None,
) -> PendingPersonEventDeletesTable:
    """Query postgres using django ORM to get pending person deletions and insert directly into ClickHouse."""

    pending_deletions = AsyncDeletion.objects.all()

    if not create_pending_person_deletions_table.is_reporting:
        pending_deletions = pending_deletions.filter(
            deletion_type=DeletionType.Person,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        )
        if create_pending_person_deletions_table.team_id:
            pending_deletions = pending_deletions.filter(
                team_id=create_pending_person_deletions_table.team_id,
            )

    # Process and insert in chunks
    chunk_size = 10000
    current_chunk = []
    total_rows = 0

    for deletion in pending_deletions.iterator():
        current_chunk.append(
            {
                "id": deletion.id,
                "deletion_type": deletion.deletion_type,
                "key": deletion.key,
                "group_type_index": deletion.group_type_index,
                "created_at": deletion.created_at,
                "delete_verified_at": deletion.delete_verified_at,
                "created_by_id": str(deletion.created_by.id) if deletion.created_by else None,
                "team_id": deletion.team_id,
            }
        )

        if len(current_chunk) >= chunk_size:
            cluster.any_host_by_role(
                Query(create_pending_person_deletions_table.populate_query, current_chunk),
                NodeRole.DATA,
            ).result()
            total_rows += len(current_chunk)
            current_chunk = []

    # Insert any remaining records
    if current_chunk:
        cluster.any_host_by_role(
            Query(create_pending_person_deletions_table.populate_query, current_chunk),
            NodeRole.DATA,
        ).result()
        total_rows += len(current_chunk)

    context.add_output_metadata(
        {
            "total_rows": dagster.MetadataValue.int(total_rows),
            "table_name": dagster.MetadataValue.text(create_pending_person_deletions_table.table_name),
        }
    )
    return create_pending_person_deletions_table


@dagster.op
def create_deletes_dict(
    load_pending_person_deletions: PendingPersonEventDeletesTable,
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingDeletesDictionary:
    """Create a dictionary in ClickHouse to store pending event deletions."""

    # Wait for the table to be fully replicated
    def sync_replica(client: Client):
        client.execute(f"SYSTEM SYNC REPLICA {load_pending_person_deletions.qualified_name} STRICT")

    cluster.map_hosts_by_role(sync_replica, NodeRole.DATA).result()

    del_dict = PendingDeletesDictionary(
        source=load_pending_person_deletions,
    )

    cluster.any_host_by_role(
        partial(
            del_dict.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
        ),
        NodeRole.DATA,
    ).result()
    return del_dict


@dagster.op
def load_and_verify_deletes_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PendingDeletesDictionary,
) -> PendingDeletesDictionary:
    """Load the dictionary data on all hosts in the cluster, and ensure all hosts have identical data."""
    checksums = cluster.map_hosts_by_role(dictionary.load, NodeRole.DATA, concurrency=1).result()
    assert len(set(checksums.values())) == 1
    return dictionary


@dagster.op
def delete_person_events(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    load_and_verify_deletes_dictionary: PendingDeletesDictionary,
) -> tuple[PendingDeletesDictionary, ShardMutations]:
    """Delete events from sharded_events table for persons pending deletion."""

    def count_pending_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count()
            FROM {load_and_verify_deletes_dictionary.qualified_name}
            """
        )
        return result[0][0] if result else 0

    count_result = cluster.map_hosts_by_role(count_pending_deletes, NodeRole.DATA).result()

    all_zero = all(count == 0 for count in count_result.values())
    if all_zero:
        context.add_output_metadata(
            {"events_deleted": dagster.MetadataValue.int(0), "message": "No pending deletions found"}
        )
        return (load_and_verify_deletes_dictionary, {})

    context.add_output_metadata(
        {
            "events_deleted": dagster.MetadataValue.int(sum(count_result.values())),
        }
    )

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (
            cluster.map_one_host_per_shard(load_and_verify_deletes_dictionary.delete_mutation_runner).result().items()
        )
    }

    return (load_and_verify_deletes_dictionary, shard_mutations)


@dagster.op
def wait_for_delete_mutations(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    delete_person_events: tuple[PendingDeletesDictionary, ShardMutations],
) -> PendingDeletesDictionary:
    pending_deletes_dict, shard_mutations = delete_person_events

    cluster.map_all_hosts_in_shards({shard: mutation.wait for shard, mutation in shard_mutations.items()}).result()

    return pending_deletes_dict


@dagster.op
def cleanup_delete_assets(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: DeleteConfig,
    create_pending_person_deletions_table: PendingPersonEventDeletesTable,
    create_deletes_dict: PendingDeletesDictionary,
    wait_for_delete_mutations: PendingDeletesDictionary,
) -> bool:
    """Clean up temporary tables and mark deletions as verified."""
    # Drop the dictionary and table using the table object

    if not config.cleanup:
        config.log.info("Skipping cleanup as cleanup is disabled")
        return True

    # Mark deletions as verified in Django
    if not create_pending_person_deletions_table.team_id:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).update(delete_verified_at=timezone.now())
    else:
        AsyncDeletion.objects.filter(
            deletion_type=DeletionType.Person,
            team_id=create_pending_person_deletions_table.team_id,
            delete_verified_at__isnull=True,
            created_at__lte=create_pending_person_deletions_table.timestamp,
        ).update(delete_verified_at=timezone.now())

    # Must drop dict first
    cluster.any_host_by_role(create_deletes_dict.drop, NodeRole.DATA).result()
    cluster.any_host_by_role(create_pending_person_deletions_table.drop, NodeRole.DATA).result()

    return True


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def deletes_job():
    """Job that handles deletion of person events."""
    oldest_override_timestamp = get_oldest_person_override_timestamp()
    report_person_table = create_reporting_pending_person_deletions_table()
    person_table = create_pending_person_deletions_table(oldest_override_timestamp)
    loaded_person_table = load_pending_person_deletions(person_table)
    create_deletes_dict_op = create_deletes_dict(loaded_person_table)
    load_dict = load_and_verify_deletes_dictionary(create_deletes_dict_op)
    delete_events = delete_person_events(load_dict)
    waited_mutation = wait_for_delete_mutations(delete_events)
    cleaned = cleanup_delete_assets(person_table, create_deletes_dict_op, waited_mutation)
    load_pending_person_deletions(report_person_table, cleaned)


@dagster.run_status_sensor(
    run_status=dagster.DagsterRunStatus.SUCCESS,
    monitored_jobs=[squash_person_overrides],
    request_job=deletes_job,
)
def run_deletes_after_squash(context):
    return dagster.RunRequest(run_key=None)
