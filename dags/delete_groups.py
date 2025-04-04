import dagster
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    NodeRole,
    LightweightDeleteMutationRunner,
)
from posthog.models.group.sql import GROUPS_TABLE
from dags.common import JobOwners


@dagster.op
def delete_groups(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """Delete groups that are marked for deletion."""
    mutation_runner = LightweightDeleteMutationRunner(GROUPS_TABLE, "is_deleted = 1")

    cluster.any_host_by_role(mutation_runner, NodeRole.DATA).result()


@dagster.job(tags={"owner": JobOwners.TEAM_CRM.value})
def delete_groups_job():
    """Job that handles deletion of groups marked as deleted."""
    delete_groups()
