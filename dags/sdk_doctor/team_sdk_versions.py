import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal, Optional

import dagster
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.schema import HogQLQueryResponse

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from dags.common import JobOwners, redis
from dags.sdk_doctor.github_sdk_versions import SDK_TYPES

default_logger = structlog.get_logger(__name__)

CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days
BATCH_SIZE = 1000

QUERY = parse_select("""
    SELECT
        properties.$lib AS lib,
        properties.$lib_version AS lib_version,
        MAX(timestamp) AS max_timestamp,
        COUNT(*) AS event_count
    FROM events
    WHERE
        timestamp >= now() - INTERVAL 7 DAY
        AND lib IS NOT NULL
        AND lib_version IS NOT NULL
    GROUP BY lib, lib_version
    ORDER BY
        lib,
        sortableSemVer(lib_version) DESC,
        event_count DESC
""")


# Avoid flakiness with ClickHouse by retrying this 2 more times if it fails
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def run_query(team: Team) -> HogQLQueryResponse:
    query_type = "sdk_versions_for_team"
    with tags_context(product=Product.SDK_DOCTOR, team_id=team.pk, org_id=team.organization_id, query_type=query_type):
        response = execute_hogql_query(QUERY, team, query_type=query_type)
    return response


def get_sdk_versions_for_team(
    team_id: int,
    *,
    logger=default_logger,
) -> Optional[dict[str, list[dict[str, Any]]]]:
    """
    Query ClickHouse for events in the last 7 days and extract SDK usage.
    Returns dict of SDK versions with minimal data, grouped by lib type.
    """
    try:
        team = Team.objects.get(id=team_id)
        response = run_query(team)

        output = defaultdict(list)
        for lib, lib_version, max_timestamp, event_count in response.results:
            if lib in SDK_TYPES:
                output[lib].append(
                    {
                        "lib_version": lib_version,
                        "max_timestamp": str(max_timestamp),
                        "count": event_count,
                    }
                )

        return dict(output)
    except Team.DoesNotExist:
        logger.exception(f"[SDK Doctor] Team {team_id} not found")
        return {}  # Safe to return empty dict, this is not an error
    except Exception as e:
        logger.exception(f"[SDK Doctor] Error querying events for team {team_id}")
        capture_exception(e, {"team_id": team_id})
        return None


def get_and_cache_team_sdk_versions(
    team_id: int,
    redis_client: redis.Redis,
    *,
    logger=default_logger,
) -> Optional[dict[str, list[dict[str, Any]]]]:
    """
    Query ClickHouse for team SDK versions and cache the result.
    Shared function used by both API and Dagster job.
    Returns the response data dict or None if failed.
    """
    try:
        sdk_versions = get_sdk_versions_for_team(team_id, logger=logger)
        if sdk_versions is not None:
            payload = json.dumps(sdk_versions)
            cache_key = f"sdk_versions:team:{team_id}"
            redis_client.setex(cache_key, CACHE_EXPIRY, payload)
            logger.info(f"[SDK Doctor] Team {team_id} SDK versions cached successfully")

            return sdk_versions
        else:
            logger.error(f"[SDK Doctor] No data received from ClickHouse for team {team_id}")
            return None
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to get and cache SDK versions for team {team_id}")
        capture_exception(e)
        return None


@dagster.op(
    out=dagster.DynamicOut(list[int]),
    config_schema={
        "team_ids": dagster.Field(
            dagster.Array(dagster.Int),
            default_value=[],
            is_required=False,
            description="Specific team IDs to process. If empty, processes all teams.",
        )
    },
)
def get_all_team_ids_op(context: dagster.OpExecutionContext):
    """Fetch all team IDs to process in batches of BATCH_SIZE."""
    override_team_ids = context.op_config["team_ids"]

    if override_team_ids:
        team_ids = override_team_ids
        context.log.info(f"Processing {len(team_ids)} configured teams: {team_ids}")
    else:
        # We have a team with id 0, but HogQL doesn't support it, so let's just skip it
        team_ids = list(Team.objects.exclude(id=0).values_list("id", flat=True))
        context.log.info(f"Processing all {len(team_ids)} teams")

    for i in range(0, len(team_ids), BATCH_SIZE):
        batch = team_ids[i : i + BATCH_SIZE]
        yield dagster.DynamicOutput(batch, mapping_key=f"batch_{i // BATCH_SIZE}")


@dataclass(kw_only=True)
class CacheTeamSdkVersionsResult:
    team_id: int
    sdk_count: int
    status: Literal["success", "empty", "failed", "error"]


@dagster.op(
    retry_policy=dagster.RetryPolicy(
        max_retries=3,
        delay=1,  # 1s
        backoff=dagster.Backoff.EXPONENTIAL,
        jitter=dagster.Jitter.PLUS_MINUS,
    )
)
def cache_team_sdk_versions_for_team_op(
    context: dagster.OpExecutionContext,
    redis_client: dagster.ResourceParam[redis.Redis],
    team_ids: list[int],
) -> list[CacheTeamSdkVersionsResult]:
    """Fetch and cache SDK versions for a batch of teams."""
    results = []

    for team_id in team_ids:
        try:
            sdk_versions = get_and_cache_team_sdk_versions(team_id, redis_client, logger=context.log)

            sdk_count = 0 if sdk_versions is None else len(sdk_versions)

            status: Literal["success", "empty", "failed", "error"] = "error"
            if sdk_versions is not None:
                if len(sdk_versions) == 0:
                    context.log.debug(f"Team {team_id} has no SDK versions")
                    status = "empty"
                else:
                    context.log.info(f"Cached {sdk_count} SDK types for team {team_id}")
                    status = "success"
            else:
                context.log.warning(f"Failed to get SDK versions for team {team_id}")
                status = "failed"

            results.append(CacheTeamSdkVersionsResult(team_id=team_id, sdk_count=sdk_count, status=status))
        except Exception as e:
            context.log.exception(f"Failed to process SDK versions for team {team_id}")
            capture_exception(e)
            results.append(CacheTeamSdkVersionsResult(team_id=team_id, sdk_count=0, status="error"))

    empty_results = [r for r in results if r.status == "empty"]
    failed_results = [r for r in results if r.status in ("failed", "error")]
    success_results = [r for r in results if r.status == "success"]

    context.add_output_metadata(
        {
            "batch_size": dagster.MetadataValue.int(len(team_ids)),
            "processed": dagster.MetadataValue.int(len(results)),
            "empty_count": dagster.MetadataValue.int(len(empty_results)),
            "failed_count": dagster.MetadataValue.int(len(failed_results)),
            "success_count": dagster.MetadataValue.int(len(success_results)),
        }
    )

    return results


@dagster.op
def aggregate_results_op(context: dagster.OpExecutionContext, results: list[list[CacheTeamSdkVersionsResult]]) -> None:
    """Aggregate results from all team processing ops."""
    flat_results = [r for batch in results for r in batch]

    total_teams = len(flat_results)
    cached_count = sum(1 for r in flat_results if r.status == "success")
    empty_count = sum(1 for r in flat_results if r.status == "empty")
    failed_count = sum(1 for r in flat_results if r.status in ("failed", "error"))

    context.log.info(
        f"Completed processing {total_teams} teams: {cached_count} cached, {empty_count} empty, {failed_count} failed"
    )

    context.add_output_metadata(
        {
            "total_teams": dagster.MetadataValue.int(total_teams),
            "cached_count": dagster.MetadataValue.int(cached_count),
            "empty_count": dagster.MetadataValue.int(empty_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
        }
    )

    if failed_count > 0:
        failed_team_ids = [r.team_id for r in flat_results if r.status in ("failed", "error")]
        raise Exception(f"Failed to cache SDK versions for {failed_count} teams: {failed_team_ids}")


@dagster.job(
    description="Queries ClickHouse for recent SDK versions and caches them in Redis",
    # Do this slowly, 10 batches at a time at most, more than this will cause the pod to OOM
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 10}),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def cache_all_team_sdk_versions_job():
    team_ids = get_all_team_ids_op()
    results = team_ids.map(cache_team_sdk_versions_for_team_op)
    aggregate_results_op(results.collect())


cache_all_team_sdk_versions_schedule = dagster.ScheduleDefinition(
    job=cache_all_team_sdk_versions_job,
    cron_schedule="0 0 * * *",  # Every day at midnight
    execution_timezone="UTC",
    name="cache_all_team_sdk_versions_schedule",
)
