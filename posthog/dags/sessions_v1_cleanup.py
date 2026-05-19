"""
Dagster job for cleaning up sessions v1 rows that don't belong to allowed teams.

The sessions v1 table (sharded_sessions) is only used by grandfathered teams listed in
ALLOWED_TEAM_IDS. This job deletes any rows for teams not in that list.
"""

import dagster

from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster, MutationWaiter
from posthog.dags.common import JobOwners
from posthog.models.sessions.sql import ALLOWED_TEAM_IDS, SESSIONS_DATA_TABLE


@dagster.op
def delete_sessions_not_in_allowed_teams(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict[int, MutationWaiter]:
    """Delete sessions v1 rows for teams not in ALLOWED_TEAM_IDS using ALTER TABLE DELETE."""

    if not ALLOWED_TEAM_IDS:
        raise ValueError("ALLOWED_TEAM_IDS must not be empty")

    allowed_ids_str = ", ".join(str(tid) for tid in ALLOWED_TEAM_IDS)
    delete_predicate = f"team_id NOT IN ({allowed_ids_str})"

    delete_mutation_runner = AlterTableMutationRunner(
        table=SESSIONS_DATA_TABLE(),
        commands={f"DELETE WHERE {delete_predicate}"},
        force=True,
    )

    context.log.info(f"Starting deletion of sessions v1 rows where {delete_predicate}")

    shard_mutations = {
        host.shard_num: mutation
        for host, mutation in cluster.map_one_host_per_shard(delete_mutation_runner).result().items()
        if host.shard_num is not None
    }

    context.add_output_metadata(
        {
            "shards_with_mutations": dagster.MetadataValue.int(len(shard_mutations)),
            "predicate": dagster.MetadataValue.text(delete_predicate),
            "allowed_team_ids": dagster.MetadataValue.text(allowed_ids_str),
        }
    )

    return shard_mutations


@dagster.op
def wait_for_sessions_delete_mutations(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    shard_mutations: dict[int, MutationWaiter],
) -> bool:
    """Wait for all deletion mutations to complete across shards."""

    if not shard_mutations:
        context.log.info("No mutations to wait for.")
        return True

    context.log.info(f"Waiting for mutations to complete on {len(shard_mutations)} shards...")

    cluster.map_all_hosts_in_shards({shard: mutation.wait for shard, mutation in shard_mutations.items()}).result()

    context.log.info("All mutations completed.")
    context.add_output_metadata({"mutations_completed": dagster.MetadataValue.int(len(shard_mutations))})

    return True


@dagster.job(tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value})
def sessions_v1_cleanup_job():
    """Job that deletes sessions v1 rows for teams not in ALLOWED_TEAM_IDS."""
    shard_mutations = delete_sessions_not_in_allowed_teams()
    wait_for_sessions_delete_mutations(shard_mutations)
