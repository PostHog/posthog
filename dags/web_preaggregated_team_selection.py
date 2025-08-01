import os

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.team_selection import (
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL,
    DEFAULT_ENABLED_TEAM_IDS,
    get_top_teams_by_median_pageviews_sql,
    DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT,
)
from dags.common import JobOwners, settings_with_log_comment


def get_teams_from_env() -> set[int]:
    env_teams = os.getenv("WEB_ANALYTICS_ENABLED_TEAM_IDS")
    if not env_teams:
        return set()

    try:
        return {int(tid.strip()) for tid in env_teams.split(",") if tid.strip()}
    except ValueError:
        return set()


def get_teams_from_top_pageviews(context: dagster.OpExecutionContext) -> set[int]:
    try:
        sql = get_top_teams_by_median_pageviews_sql(DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT)
        result = sync_execute(sql)
        return {row[0] for row in result}
    except ValueError as e:
        context.log.error(f"Invalid configuration for pageviews query: {e}")  # noqa: TRY400
        return set()
    except Exception as e:
        context.log.warning(f"Failed to fetch top teams by pageviews: {e}")
        return set()


def get_teams_from_feature_enrollment(
    context: dagster.OpExecutionContext, flag_key: str = "web-analytics-enabled"
) -> set[int]:
    """Get teams where users have enrolled in a feature preview"""
    try:
        from posthog.models.person.person import Person

        # Query PostgreSQL for teams with enrolled users
        enrollment_key = f"$feature_enrollment/{flag_key}"
        team_ids = (
            Person.objects.filter(**{f"properties__{enrollment_key}": True})
            .values_list("team_id", flat=True)
            .distinct()
        )

        team_ids_set = set(team_ids)
        context.log.info(f"Found {len(team_ids_set)} teams with users enrolled in '{flag_key}'")
        return team_ids_set

    except Exception as e:
        context.log.warning(f"Failed to get teams with feature enrollment for '{flag_key}': {e}")
        return set()


def validate_team_ids(context: dagster.OpExecutionContext, team_ids: set[int]) -> set[int]:
    """Validate that team IDs exist in the database"""
    if not team_ids:
        return team_ids

    try:
        from posthog.models.team.team import Team

        # Check which teams exist
        existing_teams = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
        invalid_teams = team_ids - existing_teams

        if invalid_teams:
            context.log.warning(
                f"Found {len(invalid_teams)} invalid team IDs that will be excluded: {sorted(invalid_teams)}"
            )

        context.log.info(f"Validated {len(existing_teams)} out of {len(team_ids)} team IDs")
        return existing_teams

    except Exception as e:
        context.log.warning(f"Failed to validate team IDs: {e}. Proceeding with unvalidated teams.")
        return team_ids


def get_team_ids_from_sources(context: dagster.OpExecutionContext) -> list[int]:
    all_team_ids = set(DEFAULT_ENABLED_TEAM_IDS)  # Always include defaults

    # Get enabled strategies from env var (comma-separated list)
    enabled_strategies = os.getenv("WEB_ANALYTICS_TEAM_STRATEGIES", "env,pageviews").split(",")
    enabled_strategies = [s.strip().lower() for s in enabled_strategies]

    # Validate strategy names
    valid_strategies = {"env", "most_pageviews", "feature_enrollment"}
    invalid_strategies = set(enabled_strategies) - valid_strategies
    if invalid_strategies:
        context.log.warning(f"Unknown strategies will be ignored: {invalid_strategies}")

    enabled_strategies = [s for s in enabled_strategies if s in valid_strategies]
    context.log.info(f"Enabled strategies: {enabled_strategies}")

    # Add teams from environment variable
    if "env" in enabled_strategies:
        env_teams = get_teams_from_env()
        all_team_ids.update(env_teams)
        context.log.info(f"Added {len(env_teams)} teams from environment variable")

    # Add teams with most pageviews
    if "most_pageviews" in enabled_strategies:
        pageview_teams = get_teams_from_top_pageviews(context)
        all_team_ids.update(pageview_teams)
        context.log.info(f"Added {len(pageview_teams)} teams from top pageviews")

    # Add teams with feature flag enrollment
    if "feature_enrollment" in enabled_strategies:
        flag_key = os.getenv("WEB_ANALYTICS_FEATURE_FLAG_KEY", "web-analytics-api")
        enrollment_teams = get_teams_from_feature_enrollment(context, flag_key)
        all_team_ids.update(enrollment_teams)
        context.log.info(f"Added {len(enrollment_teams)} teams from feature enrollment")

    # Validate team IDs exist
    validated_team_ids = validate_team_ids(context, all_team_ids)

    team_list = sorted(validated_team_ids)
    context.log.info(f"Total validated team IDs: {len(team_list)}")
    return team_list


def store_team_selection_in_clickhouse(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    context.log.info(f"Storing {len(team_ids)} enabled team IDs in ClickHouse")

    if not team_ids:
        context.log.warning("No team IDs to store")
        return team_ids

    def insert(client: Client) -> bool:
        try:
            client.execute(
                WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL(team_ids),
                settings=settings_with_log_comment(context),
            )
            context.log.info("Successfully inserted team selection")
            return True
        except Exception as e:
            context.log.warning(f"Failed to insert team selection: {e}")
            return False

    def reload_dict(client: Client) -> bool:
        try:
            client.execute(
                f"SYSTEM RELOAD DICTIONARY {WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}",
                settings=settings_with_log_comment(context),
            )
            context.log.info("Successfully reloaded team selection dictionary")
            return True
        except Exception as e:
            context.log.warning(f"Failed to reload team selection dictionary: {e}")
            return False

    # Execute operations on all hosts
    insert_results = cluster.map_all_hosts(insert).result()
    reload_results = cluster.map_all_hosts(reload_dict).result()

    # Check if all operations succeeded
    if not all(insert_results.values()):
        raise Exception(f"Failed to insert team selection on some hosts: {insert_results}")

    if not all(reload_results.values()):
        raise Exception(f"Failed to reload dictionary on some hosts: {reload_results}")

    return team_ids


@dagster.asset(
    name="web_analytics_team_selection",
    group_name="web_analytics",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_team_selection(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Materializes web analytics team selection into ClickHouse.

    This asset manages which teams have access to web analytics pre-aggregated tables.
    The selection is then stored in a ClickHouse dictionary for fast lookups.
    """
    context.log.info("Getting team IDs from sources")
    team_ids = get_team_ids_from_sources(context)

    context.log.info(f"Materializing team selection for {len(team_ids)} teams")
    stored_team_ids = store_team_selection_in_clickhouse(context, team_ids, cluster)

    context.log.info(f"Successfully materialized team selection for {len(stored_team_ids)} teams")

    return dagster.MaterializeResult(
        metadata={
            "team_count": len(stored_team_ids),
            "team_ids": str(stored_team_ids),
        }
    )
