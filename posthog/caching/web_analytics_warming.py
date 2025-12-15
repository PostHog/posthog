import json
from datetime import UTC, datetime, timedelta

from django.db.models import Q

import structlog
import posthoganalytics
from celery import shared_task
from celery.canvas import chain
from prometheus_client import Counter, Gauge

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import process_query_dict
from posthog.caching.utils import largest_teams
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting
from posthog.ph_client import ph_scoped_capture
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

STALE_WEB_QUERIES_GAUGE = Gauge(
    "posthog_cache_warming_stale_web_query_gauge",
    "Number of stale web queries present",
    ["team_id"],
)
PRIORITY_WEB_QUERIES_COUNTER = Counter(
    "posthog_cache_warming_priority_web_queries",
    "Number of priority web queries warmed",
    ["team_id", "normalized_query_hash", "is_cached"],
)


def teams_enabled_for_web_analytics_cache_warming() -> list[int]:
    enabled_team_ids = []

    for team_id, organization_id, uuid in Team.objects.values_list(
        "id",
        "organization_id",
        "uuid",
    ).iterator(chunk_size=1000):
        enabled = posthoganalytics.feature_enabled(
            "web-analytics-cache-warming",
            str(uuid),
            groups={
                "organization": str(organization_id),
                "project": str(team_id),
            },
            group_properties={
                "organization": {
                    "id": str(organization_id),
                },
                "project": {
                    "id": str(team_id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

        if enabled:
            enabled_team_ids.append(team_id)

    return enabled_team_ids


def queries_to_keep_fresh(team_id: int, days: int = 7, minimum_query_count: int = 10) -> list[dict]:
    results = sync_execute(
        """
        SELECT
            team_id,
            query_json_raw,
            COUNT(*) AS query_count,
            normalizedQueryHash(query) as normalized_query_hash
        FROM (
            SELECT
                team_id,
                JSONExtractRaw(log_comment, 'query') AS query_json_raw,
                query
            FROM metrics_query_log_mv
            WHERE
                timestamp >= now() - INTERVAL %(days)s DAY
                AND team_id = %(team_id)s
                AND query_type IN (
                    'stats_table_query',
                    'web_goals_query',
                    'web_overview_preaggregated_query',
                    'web_overview_query',
                    'web_vitals_path_breakdown_query'
                )
        ) AS sub
        GROUP BY
            team_id,
            query_json_raw,
            normalized_query_hash
        HAVING query_count >= %(minimum_query_count)s
        ORDER BY
            query_count DESC
        """,
        {"team_id": team_id, "days": days, "minimum_query_count": minimum_query_count},
    )

    logger.info("Frequent web analytics queries", team_id=team_id, query_count=len(results))

    return [
        {
            "team_id": result[0],
            "query_json": json.loads(result[1]),
            "query_count": result[2],
            "normalized_query_hash": result[3],
        }
        for result in results
    ]


@shared_task(ignore_result=True, expires=60 * 15)
def schedule_web_analytics_warming_for_teams_task():
    team_ids = largest_teams(limit=10)

    enabled_teams = Team.objects.filter(
        Q(pk__in=team_ids)
        | Q(extra_settings__insights_cache_warming=True)
        | Q(pk__in=teams_enabled_for_web_analytics_cache_warming())
    )

    expire_after = datetime.now(UTC) + timedelta(minutes=50)

    days = get_instance_setting("WEB_ANALYTICS_WARMING_DAYS")
    minimum_query_count = get_instance_setting("WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT")

    with ph_scoped_capture() as capture_ph_event:
        for team in enabled_teams:
            queries = queries_to_keep_fresh(
                team.id,
                days=days,
                minimum_query_count=minimum_query_count,
            )

            STALE_WEB_QUERIES_GAUGE.labels(team_id=team.id).set(len(queries))

            capture_ph_event(
                distinct_id=str(team.uuid),
                event="cache warming - web queries to cache",
                properties={
                    "count": len(queries),
                    "team_id": team.id,
                    "organization_id": team.organization_id,
                },
            )

            chain(
                *(
                    warm_web_analytics_cache_task.si(
                        team.id,
                        query["query_json"],
                        query["normalized_query_hash"],
                    ).set(expires=expire_after)
                    for query in queries
                )
            )()


@shared_task(
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    ignore_result=True,
    expires=60 * 60,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=2,
    retry_backoff_max=3,
    max_retries=3,
)
def warm_web_analytics_cache_task(team_id: int, query_json: dict, normalized_query_hash: str):
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.info("Warming web analytics cache failed - team not found", team_id=team_id)
        return

    tag_queries(team_id=team_id, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

    logger.info("Warming web analytics cache", team_id=team_id, normalized_query_hash=normalized_query_hash)

    try:
        results = process_query_dict(
            team,
            query_json,
            limit_context=LimitContext.QUERY_ASYNC,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        )

        is_cached = getattr(results, "is_cached", False)

        PRIORITY_WEB_QUERIES_COUNTER.labels(
            team_id=team_id,
            normalized_query_hash=normalized_query_hash,
            is_cached=is_cached,
        ).inc()

        with ph_scoped_capture() as capture_ph_event:
            capture_ph_event(
                distinct_id=str(team.uuid),
                event="cache warming - warming web query",
                properties={
                    "is_cached": is_cached,
                    "team_id": team_id,
                    "organization_id": team.organization_id,
                    "normalized_query_hash": normalized_query_hash,
                },
            )

    except CHQueryErrorTooManySimultaneousQueries:
        raise
    except Exception as e:
        capture_exception(e)
