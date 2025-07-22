import os

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.team_config import (
    WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_NAME,
    WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL,
    DEFAULT_ENABLED_TEAM_IDS,
)
from dags.common import JobOwners, settings_with_log_comment


class WebAnalyticsTeamConfig(dagster.Config):
    enabled_team_ids: list[int] = DEFAULT_ENABLED_TEAM_IDS


def get_team_ids_from_sources() -> list[int]:
    team_ids = set()

    env_teams = os.getenv("WEB_ANALYTICS_ENABLED_TEAM_IDS")
    if env_teams:
        try:
            env_team_list = [int(tid.strip()) for tid in env_teams.split(",")]
            team_ids.update(env_team_list)
        except ValueError:
            pass

    # TODO: Get teams from feature preview, or settings

    # Fallback to default teams if no other sources provided data
    if not team_ids:
        team_ids.update(DEFAULT_ENABLED_TEAM_IDS)

    return sorted(team_ids)


def store_team_config_in_clickhouse(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    context.log.info(f"Storing {len(team_ids)} enabled team IDs in ClickHouse")

    if team_ids:

        def insert(client: Client) -> bool:
            try:
                client.execute(
                    WEB_ANALYTICS_TEAM_CONFIG_DATA_SQL(team_ids),
                    settings=settings_with_log_comment(context),
                )
                context.log.info("Successfully inserted team configuration")
                return True
            except Exception as e:
                context.log.warning(f"Failed to insert team configuration: {e}")
                return False

        def reload_dict(client: Client) -> bool:
            try:
                client.execute(
                    f"SYSTEM RELOAD DICTIONARY {WEB_ANALYTICS_TEAM_CONFIG_DICTIONARY_NAME}",
                    settings=settings_with_log_comment(context),
                )
                context.log.info("Successfully reloaded team config dictionary")
                return True
            except Exception as e:
                context.log.warning(f"Failed to reload team config dictionary: {e}")
                return False

        insert_results = cluster.map_all_hosts(insert).result()
        reload_results = cluster.map_all_hosts(reload_dict).result()

        if not all(insert_results.values()):
            raise Exception(f"Failed to insert team configuration on some hosts: {insert_results}")

        if not all(reload_results.values()):
            raise Exception(f"Failed to reload dictionary on some hosts: {reload_results}")

    else:
        context.log.warning("No team IDs to store")

    return team_ids


@dagster.asset(
    name="web_analytics_team_config",
    group_name="web_analytics",
    config_schema=WebAnalyticsTeamConfig,
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_team_config(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Materializes web analytics team configuration into ClickHouse.

    This asset manages which teams have access to web analytics pre-aggregated tables.
    The configuration is then stored in a ClickHouse dictionary for fast lookups.
    """
    config = context.op_config

    context.log.info(f"Getting team IDs from sources: {config}")
    team_ids = (
        config.enabled_team_ids if config.enabled_team_ids != DEFAULT_ENABLED_TEAM_IDS else get_team_ids_from_sources()
    )

    context.log.info(f"Materializing team configuration for {len(team_ids)} teams")
    stored_team_ids = store_team_config_in_clickhouse(context, team_ids, cluster)

    context.log.info(f"Successfully materialized team configuration for {len(stored_team_ids)} teams")

    return dagster.MaterializeResult(
        metadata={
            "team_count": len(stored_team_ids),
            "team_ids": str(stored_team_ids),
        }
    )
