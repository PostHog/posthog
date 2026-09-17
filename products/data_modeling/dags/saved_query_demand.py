"""Turn the saved-query tags in the ClickHouse query log into a per-node "last read" timestamp.

Every HogQL query records the saved queries it read in `log_comment.saved_query_ids`. Once a day this job
folds one day of the archive into (team, saved query, last read time) and hands each team's slice to the
data modeling facade, which stamps the nodes and their ancestors.
"""

from collections import defaultdict
from datetime import UTC, datetime

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.resources import OpsClickhouseClusterResource

from products.data_modeling.backend.facade.api import record_saved_query_demand

ONE_GB = 1024 * 1024 * 1024

# Refresh runs read a model's parents to rebuild it; that is the system's demand, not a person's.
DEMAND_QUERY = """
SELECT team_id, saved_query_id, max(event_time) AS last_read_at
FROM posthog.query_log_archive
ARRAY JOIN lc_saved_query_ids AS saved_query_id
WHERE event_date = %(day)s
  AND is_initial_query
  AND notEmpty(lc_saved_query_ids)
  AND lc_feature != 'data_modeling'
GROUP BY team_id, saved_query_id
"""

daily_partitions = dagster.DailyPartitionsDefinition(start_date="2026-09-17", timezone="UTC")


@dagster.op
def record_saved_query_demand_day(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    day = context.partition_key

    def run(client: Client) -> list[tuple[int, str, datetime]]:
        return client.execute(DEMAND_QUERY, {"day": day}, settings=settings_with_log_comment(context))

    rows = cluster.any_host_by_role(run, NodeRole.OPS).result()

    demand_by_team: dict[int, dict[str, datetime]] = defaultdict(dict)
    for team_id, saved_query_id, last_read_at in rows:
        demand_by_team[team_id][saved_query_id] = last_read_at.replace(tzinfo=UTC)

    nodes_stamped = 0
    failed_teams: list[int] = []
    for team_id, last_read_at_by_query in demand_by_team.items():
        try:
            nodes_stamped += record_saved_query_demand(team_id, last_read_at_by_query)
        except Exception:
            failed_teams.append(team_id)
            context.log.exception(f"Failed to record saved query demand for team {team_id} on {day}")

    context.add_output_metadata(
        {
            "day": day,
            "saved_queries_read": len(rows),
            "teams": len(demand_by_team),
            "nodes_stamped": nodes_stamped,
            "failed_teams": len(failed_teams),
        }
    )
    if failed_teams:
        raise dagster.Failure(f"Saved query demand for {day} failed for {len(failed_teams)} team(s): {failed_teams}")


@dagster.job(
    partitions_def=daily_partitions,
    resource_defs={"cluster": OpsClickhouseClusterResource(max_execution_time=30 * 60, max_memory_usage=8 * ONE_GB)},
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value},
)
def record_saved_query_demand_job():
    record_saved_query_demand_day()


record_saved_query_demand_schedule = dagster.build_schedule_from_partitioned_job(
    record_saved_query_demand_job,
    hour_of_day=2,
    minute_of_hour=0,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
