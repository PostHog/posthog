import abc
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
from django.db.models import Q
from more_itertools import chunked

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    MutationWaiter,
    LightweightDeleteMutationRunner,
    NodeRole,
    Query,
)
from posthog.clickhouse.plugin_log_entries import PLUGIN_LOG_ENTRIES_TABLE
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import (
    PERSON_DISTINCT_ID2_TABLE,
    PERSON_DISTINCT_ID_OVERRIDES_TABLE,
    PERSON_STATIC_COHORT_TABLE,
    PERSONS_TABLE,
)
from posthog.models.group.sql import GROUPS_TABLE

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
class Table:
    @property
    @abc.abstractmethod
    def table_name(self) -> str:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def qualified_name(self):
        raise NotImplementedError()


@dataclass
class PendingDeletesTable(Table):
    """
    Represents a table storing pending deletions.
    """

    timestamp: datetime
    team_id: int | None = None

    @property
    def timestamp_isoformat(self) -> str:
        return self.timestamp.isoformat()

    @property
    def clickhouse_timestamp(self) -> str:
        return self.timestamp.strftime("%Y%m%d_%H%M%S")

    @property
    def table_name(self) -> str:
        return f"pending_deletes_{self.clickhouse_timestamp}"

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
            CREATE TABLE IF NOT EXISTS {self.qualified_name}
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
            SETTINGS replicated_can_become_leader = 1
        """

    @property
    def truncate_table_query(self) -> str:
        return f"TRUNCATE TABLE {self.qualified_name}"

    @property
    def drop_table_query(self) -> str:
        return f"DROP TABLE IF EXISTS {self.qualified_name}"

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


class AdhocEventDeletesTable(Table):
    @property
    def table_name(self) -> str:
        return ADHOC_EVENTS_DELETION_TABLE

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    def optimize(self, client: Client) -> None:
        # This is a pretty small table and has a TTL of 3 months, so we can optimize it.
        client.execute(f"OPTIMIZE TABLE {self.qualified_name} FINAL")


@dataclass
class Dictionary(abc.ABC):
    source: Table

    @property
    def name(self) -> str:
        return f"{self.source.table_name}_dictionary"

    @property
    def qualified_name(self):
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    @property
    @abc.abstractmethod
    def query(self) -> str:
        raise NotImplementedError()

    @abc.abstractmethod
    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        raise NotImplementedError()

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

        return self.checksum(client)

    @abc.abstractmethod
    def checksum(self, client: Client) -> int:
        raise NotImplementedError()


@dataclass
class PendingDeletesDictionary(Dictionary):
    source: PendingDeletesTable

    @property
    def query(self) -> str:
        return f"SELECT team_id, deletion_type, key, created_at FROM {self.source.qualified_name}"

    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                deletion_type UInt8,
                key String,
                created_at DateTime,
            )
            PRIMARY KEY team_id, deletion_type, key
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

    def checksum(self, client: Client) -> int:
        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, key)
            """
        )
        [[checksum]] = results
        return checksum


@dataclass
class AdhocEventDeletesDictionary(Dictionary):
    source: AdhocEventDeletesTable

    @property
    def query(self) -> str:
        return f"SELECT team_id, uuid, created_at FROM {self.source.qualified_name} WHERE (team_id, uuid) not in (SELECT team_id, uuid FROM {self.source.qualified_name} WHERE is_deleted = 1)"

    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                uuid UUID,
                created_at DateTime64(6, 'UTC')
            )
            PRIMARY KEY team_id, uuid
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

    def checksum(self, client: Client) -> int:
        results = client.execute(
            f"""
            SELECT groupBitXor(row_checksum) AS table_checksum
            FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, uuid)
            """
        )
        [[checksum]] = results
        return checksum


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
def create_pending_deletions_table(
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    oldest_person_override_timestamp: datetime,
) -> PendingDeletesTable:
    """
    Create a merge tree table in ClickHouse to store pending deletes.

    Important to note: we only get pending Person deletions for requests that happened before the oldest person override timestamp. The other type of deletions are not limited by this timestamp.
    """

    table = PendingDeletesTable(
        timestamp=oldest_person_override_timestamp,
        team_id=config.team_id,
    )
    cluster.map_all_hosts(table.create).result()
    return table


@dagster.op
def load_pending_deletions(
    context: dagster.OpExecutionContext,
    create_pending_deletions_table: PendingDeletesTable,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingDeletesTable:
    """Query postgres using django ORM to get pending deletions and insert directly into ClickHouse."""

    pending_deletions = AsyncDeletion.objects.filter(
        Q(deletion_type=DeletionType.Person, created_at__lte=create_pending_deletions_table.timestamp)
        | Q(deletion_type=DeletionType.Team),
        delete_verified_at__isnull=True,
    )
    if create_pending_deletions_table.team_id:
        pending_deletions = pending_deletions.filter(team_id=create_pending_deletions_table.team_id)

    # Process and insert in chunks
    total_rows = 0
    for chunk in chunked(pending_deletions.iterator(), n=10000):
        cluster.any_host_by_role(
            Query(
                create_pending_deletions_table.populate_query,
                [
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
                    for deletion in chunk
                ],
            ),
            NodeRole.DATA,
        ).result()
        total_rows += len(chunk)

    context.add_output_metadata(
        {
            "total_rows": dagster.MetadataValue.int(total_rows),
            "table_name": dagster.MetadataValue.text(create_pending_deletions_table.table_name),
        }
    )
    return create_pending_deletions_table


@dagster.op
def create_deletes_dict(
    load_pending_deletions: PendingDeletesTable,
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingDeletesDictionary:
    """Create a dictionary in ClickHouse to store pending event deletions."""

    # Wait for the table to be fully replicated
    def sync_replica(client: Client):
        client.execute(f"SYSTEM SYNC REPLICA {load_pending_deletions.qualified_name} STRICT")

    cluster.map_all_hosts(sync_replica).result()

    del_dict = PendingDeletesDictionary(
        source=load_pending_deletions,
    )

    cluster.map_all_hosts(
        partial(
            del_dict.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
        )
    ).result()
    return del_dict


@dagster.op
def create_adhoc_event_deletes_dict(
    config: DeleteConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> AdhocEventDeletesDictionary:
    """Create a dictionary in ClickHouse to store pending event deletions."""

    adhoc_event_deletions = AdhocEventDeletesTable()

    # Wait for the table to be fully replicated
    def sync_replica(client: Client):
        client.execute(f"SYSTEM SYNC REPLICA {adhoc_event_deletions.qualified_name} STRICT")

    cluster.map_all_hosts(sync_replica).result()

    del_dict = AdhocEventDeletesDictionary(
        source=adhoc_event_deletions,
    )

    cluster.map_all_hosts(
        partial(
            del_dict.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
        )
    ).result()

    return del_dict


@dagster.op
def load_and_verify_deletes_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PendingDeletesDictionary,
) -> PendingDeletesDictionary:
    """Load the dictionary data on all hosts in the cluster, and ensure all hosts have identical data."""
    checksums = cluster.map_all_hosts(dictionary.load, concurrency=1).result()
    assert len(set(checksums.values())) == 1
    return dictionary


@dagster.op
def load_and_verify_adhoc_event_deletes_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: AdhocEventDeletesDictionary,
) -> AdhocEventDeletesDictionary:
    """Load the dictionary data on all hosts in the cluster, and ensure all hosts have identical data."""
    checksums = cluster.map_all_hosts(dictionary.load, concurrency=1).result()
    assert len(set(checksums.values())) == 1
    return dictionary


@dagster.op
def delete_events(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    load_and_verify_deletes_dictionary: PendingDeletesDictionary,
    load_and_verify_adhoc_event_deletes_dictionary: AdhocEventDeletesDictionary,
) -> tuple[PendingDeletesDictionary, ShardMutations]:
    """Delete events from sharded_events table for pending deletions."""

    def count_pending_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count()
            FROM {load_and_verify_deletes_dictionary.qualified_name}
            WHERE deletion_type IN ({DeletionType.Person}, {DeletionType.Team})
            """
        )
        return result[0][0] if result else 0

    def count_pending_adhoc_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count() as pending
            FROM {load_and_verify_adhoc_event_deletes_dictionary.qualified_name}
            """
        )
        return result[0][0] if result else 0

    count_result = cluster.map_hosts_by_role(count_pending_deletes, NodeRole.DATA).result()
    count_adhoc_result = cluster.map_hosts_by_role(count_pending_adhoc_deletes, NodeRole.DATA).result()

    all_zero = all(count == 0 for count in count_result.values()) and all(
        count == 0 for count in count_adhoc_result.values()
    )
    if all_zero:
        context.add_output_metadata(
            {"events_deleted": dagster.MetadataValue.int(0), "message": "No pending deletions found"}
        )
        return (load_and_verify_deletes_dictionary, {})

    context.add_output_metadata(
        {
            "events_deleted": dagster.MetadataValue.int(sum(count_result.values())),
            "adhoc_events_deleted": dagster.MetadataValue.int(sum(count_adhoc_result.values())),
        }
    )

    delete_mutation_runner = LightweightDeleteMutationRunner(
        table=EVENTS_DATA_TABLE(),
        predicate="""or(
            (dictHas(%(pending_deletes_dictionary)s, (team_id, %(person_deletion_type)s, person_id)) AND timestamp <= dictGet(%(pending_deletes_dictionary)s, 'created_at', (team_id, %(person_deletion_type)s, person_id))),
            (dictHas(%(pending_deletes_dictionary)s, (team_id, %(team_deletion_type)s, team_id))),
            (dictHas(%(adhoc_event_deletes_dictionary)s, (team_id, uuid)))
        )
        """,
        parameters={
            "pending_deletes_dictionary": load_and_verify_deletes_dictionary.qualified_name,
            "person_deletion_type": DeletionType.Person,
            "team_deletion_type": DeletionType.Team,
            "adhoc_event_deletes_dictionary": load_and_verify_adhoc_event_deletes_dictionary.qualified_name,
        },
    )

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in (cluster.map_one_host_per_shard(delete_mutation_runner).result().items())
    }

    return (load_and_verify_deletes_dictionary, shard_mutations)


def delete_team_data(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table_name,
    load_and_verify_deletes_dictionary: PendingDeletesDictionary,
) -> tuple[PendingDeletesDictionary, MutationWaiter | None]:
    """Delete data from the specified table for teams pending deletion."""

    def count_pending_deletes(client: Client) -> int:
        result = client.execute(
            f"""
            SELECT count()
            FROM {load_and_verify_deletes_dictionary.qualified_name}
            WHERE deletion_type IN ({DeletionType.Team})
            """
        )
        return result[0][0] if result else 0

    count_result = cluster.map_hosts_by_role(count_pending_deletes, NodeRole.DATA).result()

    all_zero = all(count == 0 for count in count_result.values())
    if all_zero:
        context.add_output_metadata(
            {
                "table_name": dagster.MetadataValue.text(table_name),
                "teams_deleted": dagster.MetadataValue.int(0),
                "message": "No pending deletions found",
            }
        )
        return (load_and_verify_deletes_dictionary, None)

    context.add_output_metadata(
        {
            "table_name": dagster.MetadataValue.text(table_name),
            "teams_deleted": dagster.MetadataValue.int(sum(count_result.values())),
        }
    )

    delete_mutation_runner = LightweightDeleteMutationRunner(
        table=table_name,
        predicate="dictHas(%(dictionary)s, (team_id, %(team_deletion_type)s, team_id))",
        parameters={
            "dictionary": load_and_verify_deletes_dictionary.qualified_name,
            "team_deletion_type": DeletionType.Team,
        },
    )

    # This mutation run on any host because it will be replicated to all shards since
    # these are replicated, non-sharded tables.
    mutation = cluster.any_host(delete_mutation_runner).result()

    return (load_and_verify_deletes_dictionary, mutation)


def delete_team_data_from(
    table: str,
) -> dagster.OpDefinition:
    @dagster.op(name=f"delete_team_data_from_{table}")
    def delete_team_data_from_op(
        context: dagster.OpExecutionContext,
        cluster: dagster.ResourceParam[ClickhouseCluster],
        load_and_verify_deletes_dictionary: PendingDeletesDictionary,
    ) -> tuple[PendingDeletesDictionary, MutationWaiter | None]:
        return delete_team_data(
            context,
            cluster,
            table,
            load_and_verify_deletes_dictionary,
        )

    return delete_team_data_from_op


@dagster.op
def wait_for_delete_mutations_in_shards(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    delete_mutations: tuple[PendingDeletesDictionary, ShardMutations],
) -> PendingDeletesDictionary:
    pending_deletes_dict, shard_mutations = delete_mutations

    cluster.map_all_hosts_in_shards({shard: mutation.wait for shard, mutation in shard_mutations.items()}).result()

    return pending_deletes_dict


@dagster.op
def wait_for_delete_mutations_in_all_hosts(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    delete_mutations: tuple[PendingDeletesDictionary, MutationWaiter | None],
) -> PendingDeletesDictionary:
    pending_deletes_dict, mutation = delete_mutations

    if mutation:
        cluster.map_all_hosts(mutation.wait).result()

    return pending_deletes_dict


@dataclass
class VerifiedDeletionResources:
    pending_deletions_dictionary: PendingDeletesDictionary
    adhoc_event_deletes_dictionary: AdhocEventDeletesDictionary


@dagster.op
def mark_deletions_verified(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    pending_deletions_dictionary: PendingDeletesDictionary,
    adhoc_event_deletes_dictionary: AdhocEventDeletesDictionary,
) -> VerifiedDeletionResources:
    now = timezone.now()
    deletion_ids = [
        id
        for (id,) in cluster.any_host_by_role(
            Query(f"SELECT id FROM {pending_deletions_dictionary.source.qualified_name}"), node_role=NodeRole.DATA
        ).result()
    ]
    for chunk in chunked(deletion_ids, n=10000):
        AsyncDeletion.objects.filter(id__in=chunk).update(delete_verified_at=now)

    # Mark adhoc event deletes as verified
    def mark_adhoc_event_deletes_done(client: Client) -> None:
        client.execute(f"""
            INSERT INTO {adhoc_event_deletes_dictionary.source.qualified_name} (team_id, uuid, created_at, deleted_at, is_deleted)
            SELECT team_id, uuid, created_at, now64(), 1
            FROM {adhoc_event_deletes_dictionary.qualified_name}
        """)

    cluster.any_host(mark_adhoc_event_deletes_done).result()

    return VerifiedDeletionResources(pending_deletions_dictionary, adhoc_event_deletes_dictionary)


@dagster.op
def cleanup_delete_assets(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: DeleteConfig,
    resources: VerifiedDeletionResources,
) -> bool:
    """Clean up temporary tables and mark deletions as verified."""
    # Drop the dictionary and table using the table object
    if not config.cleanup:
        config.log.info("Skipping cleanup as cleanup is disabled")
        return True

    # Must drop dict first
    cluster.map_all_hosts(resources.pending_deletions_dictionary.drop).result()
    cluster.map_all_hosts(resources.pending_deletions_dictionary.source.drop).result()

    cluster.map_all_hosts(resources.adhoc_event_deletes_dictionary.drop).result()
    cluster.any_host(resources.adhoc_event_deletes_dictionary.source.optimize).result()

    return True


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def deletes_job():
    """Job that handles deletion of events."""
    # Prepare requested deletions data
    oldest_override_timestamp = get_oldest_person_override_timestamp()
    deletions_table = load_pending_deletions(create_pending_deletions_table(oldest_override_timestamp))
    pending_deletes_dictionary = load_and_verify_deletes_dictionary(create_deletes_dict(deletions_table))
    adhoc_event_deletes_dictionary = load_and_verify_adhoc_event_deletes_dictionary(create_adhoc_event_deletes_dict())

    # Delete all data requested
    delete_mutations = delete_events(pending_deletes_dictionary, adhoc_event_deletes_dictionary)
    pending_deletes_dictionary = wait_for_delete_mutations_in_shards(delete_mutations)

    for table in [
        PERSON_DISTINCT_ID2_TABLE,
        PERSONS_TABLE,
        GROUPS_TABLE,
        # Disable cohortpeople data deletion for now, the mutations run here overload the cluster pretty badly
        # "cohortpeople",
        PERSON_STATIC_COHORT_TABLE,
        PLUGIN_LOG_ENTRIES_TABLE,
    ]:
        # NOTE: the reassignment of `pending_deletes_dictionary` below causes these ops to be run serially, since the
        # input to each step is the output of the previous step
        delete_mutations = delete_team_data_from(table)(pending_deletes_dictionary)
        pending_deletes_dictionary = wait_for_delete_mutations_in_all_hosts(delete_mutations)

    verified_deletion_resources = mark_deletions_verified(pending_deletes_dictionary, adhoc_event_deletes_dictionary)

    # Clean up
    cleanup_delete_assets(verified_deletion_resources)


@dagster.run_status_sensor(
    run_status=dagster.DagsterRunStatus.SUCCESS,
    monitored_jobs=[squash_person_overrides],
    request_job=deletes_job,
)
def run_deletes_after_squash(context):
    return dagster.RunRequest(run_key=None)
