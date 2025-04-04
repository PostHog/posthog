import pydantic
from dataclasses import dataclass
import dagster
from django.conf import settings
from clickhouse_driver.client import Client
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    NodeRole,
)
from posthog.models.group.sql import GROUPS_TABLE
from dags.common import JobOwners
import uuid


class DeleteGroupsConfig(dagster.Config):
    cleanup: bool = pydantic.Field(
        default=True,
        description="If true, the temporary table will be dropped after the job is run.",
    )


@dataclass
class PendingGroupDeletesTable:
    """
    Represents a table storing pending group deletions.
    """

    table_id: str
    cluster: str = settings.CLICKHOUSE_CLUSTER

    @property
    def table_name(self) -> str:
        return f"pending_group_deletes_{self.table_id}"

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
                group_type_index Int64,
                group_key String,
                team_id Int64,
                created_at DateTime
            )
            ENGINE = ReplicatedReplacingMergeTree('{self.zk_path}', '{{shard}}-{{replica}}')
            ORDER BY (team_id, group_type_index, group_key)
        """

    def create(self, client: Client) -> None:
        client.execute(self.create_table_query)

    def drop(self, client: Client) -> None:
        client.execute(f"DROP TABLE IF EXISTS {self.qualified_name} ON CLUSTER '{self.cluster}'")

    def exists(self, client: Client) -> bool:
        result = client.execute(
            f"SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(table_name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table_name": self.table_name},
        )
        return bool(result[0][0]) if result else False


@dagster.op
def create_pending_group_deletions_table(
    config: DeleteGroupsConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingGroupDeletesTable:
    """Create a merge tree table in ClickHouse to store pending group deletes."""
    table = PendingGroupDeletesTable(
        table_id=str(uuid.uuid4())[:8],
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
    cluster.any_host_by_role(table.create, NodeRole.DATA).result()
    return table


@dagster.op
def load_deleted_groups(
    context: dagster.OpExecutionContext,
    table: PendingGroupDeletesTable,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PendingGroupDeletesTable:
    """Load deleted groups into the pending deletes table."""

    query = f"""
        INSERT INTO {table.qualified_name}
        SELECT
            group_type_index,
            group_key,
            team_id,
            created_at
        FROM {GROUPS_TABLE}
        WHERE is_deleted = 1
    """

    cluster.any_host_by_role(lambda client: client.execute(query), NodeRole.DATA).result()

    verify_query = f"SELECT count() FROM {table.qualified_name}"
    [[loaded_count]] = cluster.any_host_by_role(lambda client: client.execute(verify_query), NodeRole.DATA).result()
    context.add_output_metadata({"groups_loaded": dagster.MetadataValue.int(loaded_count)})

    return table


@dagster.op
def cleanup_delete_assets(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: DeleteGroupsConfig,
    table: PendingGroupDeletesTable,
) -> None:
    """Clean up temporary tables used for deletion."""
    if config.cleanup:
        cluster.any_host_by_role(table.drop, NodeRole.DATA).result()


@dagster.job(tags={"owner": JobOwners.TEAM_CRM.value})
def delete_groups_job():
    """Job that handles deletion of groups marked as deleted."""
    table = create_pending_group_deletions_table()
    loaded_table = load_deleted_groups(table)
    cleanup_delete_assets(table=loaded_table)
