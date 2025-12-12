import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from cachetools import cached
from celery import shared_task
from dateutil import parser
from posthoganalytics.client import Client as PostHogClient
from retry import retry

from posthog.schema import AIEventType

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed_log
from posthog.models.property.util import get_property_string_expr
from posthog.models.team.team import Team
from posthog.tasks.report_utils import capture_event
from posthog.tasks.utils import CeleryQueue
from posthog.utils import get_instance_region, get_previous_day

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


@cached(cache={})
def get_ph_client() -> PostHogClient:
    """Get a PostHog client instance for capturing events."""
    return PostHogClient("sTMFPsFhdP1Ssg", sync_mode=True)


# AI events dynamically generated from AIEventType enum
AI_EVENTS = [event.value for event in AIEventType]

# ClickHouse query settings for LLM Analytics queries
CH_LLM_ANALYTICS_SETTINGS = {
    "max_execution_time": 5 * 60,  # 5 minutes
}

# Query retry configuration
QUERY_RETRIES = 3
QUERY_RETRY_DELAY = 1
QUERY_RETRY_BACKOFF = 2

# Celery task ID for query attribution
CELERY_TASK_ID = "posthog.tasks.llm_analytics_usage_report.send_llm_analytics_usage_reports"


@dataclass
class TeamMetrics:
    """All metrics for a single team from the combined query."""

    team_id: int

    # Event counts
    ai_generation_count: int = 0
    ai_embedding_count: int = 0
    ai_span_count: int = 0
    ai_trace_count: int = 0
    ai_metric_count: int = 0
    ai_feedback_count: int = 0
    ai_evaluation_count: int = 0

    # Cost metrics
    total_cost: float = 0.0
    input_cost: float = 0.0
    output_cost: float = 0.0
    request_cost: float = 0.0
    web_search_cost: float = 0.0

    # Token metrics
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class TeamDimensionBreakdowns:
    """All dimension breakdowns for a single team."""

    team_id: int
    model_breakdown: dict[str, int]
    provider_breakdown: dict[str, int]
    framework_breakdown: dict[str, int]
    library_breakdown: dict[str, int]
    cost_model_used_breakdown: dict[str, int]
    cost_model_source_breakdown: dict[str, int]
    cost_model_provider_breakdown: dict[str, int]


def _execute_split_query(
    begin: datetime,
    end: datetime,
    query_template: str,
    params: dict,
    num_splits: int = 2,
    combine_results_func: Any | None = None,
    team_ids: list[int] | None = None,
    query_name: str = "split_query",
) -> Any:
    """
    Helper function to execute a query split into multiple parts to reduce memory load.
    Splits the time period into num_splits parts and runs separate queries, then combines the results.

    Args:
        begin: Start of the time period
        end: End of the time period
        query_template: SQL query template with %(begin)s and %(end)s placeholders
        params: Additional parameters for the query
        num_splits: Number of time splits to make (default: 2)
        combine_results_func: Optional function to combine results from multiple queries
                             If None, uses the default team_id count combiner
        team_ids: Optional list of team_ids to filter by (for query optimization)

    Returns:
        Combined query results
    """
    if num_splits < 1:
        raise ValueError("num_splits must be at least 1")

    # Calculate the time interval for each split
    time_delta = (end - begin) / num_splits

    all_results = []

    # Execute query for each time split
    for i in range(num_splits):
        split_begin = begin + (time_delta * i)
        split_end = begin + (time_delta * (i + 1))

        # For the last split, use the exact end time to avoid rounding issues
        if i == num_splits - 1:
            split_end = end

        # Create a copy of params and update with the split time range
        split_params = params.copy()
        split_params["begin"] = split_begin
        split_params["end"] = split_end

        if team_ids is not None:
            split_params["team_ids"] = team_ids

        # Execute the query for this time split
        with tags_context(
            product=Product.LLM_ANALYTICS,
            kind="celery",
            id=CELERY_TASK_ID,
            name=query_name,
            workload=Workload.OFFLINE.value,
        ):
            split_result = sync_execute(
                query_template,
                split_params,
                workload=Workload.OFFLINE,
                settings=CH_LLM_ANALYTICS_SETTINGS,
            )

        all_results.append(split_result)

    # If no custom combine function is provided, use the default team_id count combiner
    if combine_results_func is None:
        return _combine_team_count_results(all_results)
    else:
        return combine_results_func(all_results)


def _combine_team_count_results(results_list: list) -> list[tuple[int, int]]:
    """
    Default function to combine results from multiple queries that return (team_id, count) tuples.

    Args:
        results_list: List of query results, each containing (team_id, count) tuples

    Returns:
        Combined list of (team_id, count) tuples
    """
    team_counts: dict[int, int] = {}

    # Combine all results
    for results in results_list:
        for row in results:
            try:
                team_id, count = row
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed row in team count results: {row}, error: {e}")
                continue

            if team_id in team_counts:
                team_counts[team_id] += count
            else:
                team_counts[team_id] = count

    # Convert back to the expected format
    return list(team_counts.items())


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_ai_events(begin: datetime, end: datetime) -> list[int]:
    """
    Get all team_ids that have at least one AI event in the period.

    This is a fast query that returns only distinct team_ids, allowing subsequent
    queries to filter by team_id and use the primary key index efficiently.
    """
    query = """
        SELECT DISTINCT team_id
        FROM events
        WHERE event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
    """

    with tags_context(
        product=Product.LLM_ANALYTICS,
        kind="celery",
        id=CELERY_TASK_ID,
        name="Get teams with AI events",
        workload=Workload.OFFLINE.value,
    ):
        results = sync_execute(
            query,
            {"ai_events": AI_EVENTS, "begin": begin, "end": end},
            workload=Workload.OFFLINE,
            settings=CH_LLM_ANALYTICS_SETTINGS,
        )

        return [row[0] for row in results]


def _combine_all_metrics_results(results_list: list) -> dict[int, TeamMetrics]:
    """
    Combine results from split queries that return all metrics per team.

    Returns:
        dict mapping team_id to TeamMetrics
    """
    team_metrics: dict[int, TeamMetrics] = {}

    for results in results_list:
        for row in results:
            if not row:
                continue

            team_id = row[0]

            if team_id not in team_metrics:
                team_metrics[team_id] = TeamMetrics(team_id=team_id)

            metrics = team_metrics[team_id]

            # Event counts (indices 1-7)
            metrics.ai_generation_count += row[1] or 0
            metrics.ai_embedding_count += row[2] or 0
            metrics.ai_span_count += row[3] or 0
            metrics.ai_trace_count += row[4] or 0
            metrics.ai_metric_count += row[5] or 0
            metrics.ai_feedback_count += row[6] or 0
            metrics.ai_evaluation_count += row[7] or 0

            # Cost metrics (indices 8-12)
            metrics.total_cost += row[8] or 0.0
            metrics.input_cost += row[9] or 0.0
            metrics.output_cost += row[10] or 0.0
            metrics.request_cost += row[11] or 0.0
            metrics.web_search_cost += row[12] or 0.0

            # Token metrics (indices 13-18)
            metrics.prompt_tokens += row[13] or 0
            metrics.completion_tokens += row[14] or 0
            metrics.total_tokens += row[15] or 0
            metrics.reasoning_tokens += row[16] or 0
            metrics.cache_read_tokens += row[17] or 0
            metrics.cache_creation_tokens += row[18] or 0

    return team_metrics


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_all_ai_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[int, TeamMetrics]:
    """
    Get all AI metrics (event counts, costs, tokens) in a single query.

    This combines what was previously 5 separate queries into one, reducing
    table scans from 5 to 1.

    Returns:
        dict mapping team_id to TeamMetrics dataclass
    """

    query_template = """
        SELECT
            team_id,
            -- Event counts by type
            countIf(event = '$ai_generation') as ai_generation_count,
            countIf(event = '$ai_embedding') as ai_embedding_count,
            countIf(event = '$ai_span') as ai_span_count,
            countIf(event = '$ai_trace') as ai_trace_count,
            countIf(event = '$ai_metric') as ai_metric_count,
            countIf(event = '$ai_feedback') as ai_feedback_count,
            countIf(event = '$ai_evaluation') as ai_evaluation_count,
            -- Cost metrics
            SUM(toFloat64OrNull(properties_group_ai['$ai_total_cost_usd'])) as total_cost,
            SUM(toFloat64OrNull(properties_group_ai['$ai_input_cost_usd'])) as input_cost,
            SUM(toFloat64OrNull(properties_group_ai['$ai_output_cost_usd'])) as output_cost,
            SUM(toFloat64OrNull(properties_group_ai['$ai_request_cost_usd'])) as request_cost,
            SUM(toFloat64OrNull(properties_group_ai['$ai_web_search_cost_usd'])) as web_search_cost,
            -- Token metrics
            SUM(toInt64OrNull(properties_group_ai['$ai_input_tokens'])) as prompt_tokens,
            SUM(toInt64OrNull(properties_group_ai['$ai_output_tokens'])) as completion_tokens,
            SUM(toInt64OrNull(properties_group_ai['$ai_total_tokens'])) as total_tokens,
            SUM(toInt64OrNull(properties_group_ai['$ai_reasoning_tokens'])) as reasoning_tokens,
            SUM(toInt64OrNull(properties_group_ai['$ai_cache_read_input_tokens'])) as cache_read_tokens,
            SUM(toInt64OrNull(properties_group_ai['$ai_cache_creation_input_tokens'])) as cache_creation_tokens
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    return _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_all_metrics_results,
        team_ids=team_ids,
        query_name="Get all AI metrics",
    )


def _merge_map_breakdowns(existing: dict[str, int], new_map: dict[str, int]) -> None:
    """Merge a new map into an existing breakdown dict, summing counts."""
    for key, value in new_map.items():
        if key in existing:
            existing[key] += value
        else:
            existing[key] = value


def _filter_breakdown(breakdown: dict[str, int], allow_empty: bool = False) -> dict[str, int]:
    """Filter out empty or whitespace-only keys from a breakdown dict."""
    if allow_empty:
        return {(k.strip() if k and k.strip() else "none"): v for k, v in breakdown.items()}

    return {k: v for k, v in breakdown.items() if k and k.strip()}


def _combine_dimension_breakdown_results(results_list: list) -> dict[int, TeamDimensionBreakdowns]:
    """
    Combine results from split queries that return dimension breakdowns using Maps.

    Returns:
        dict mapping team_id to TeamDimensionBreakdowns
    """
    team_breakdowns: dict[int, TeamDimensionBreakdowns] = {}

    for results in results_list:
        for row in results:
            if not row:
                continue

            team_id = row[0]

            if team_id not in team_breakdowns:
                team_breakdowns[team_id] = TeamDimensionBreakdowns(
                    team_id=team_id,
                    model_breakdown={},
                    provider_breakdown={},
                    framework_breakdown={},
                    library_breakdown={},
                    cost_model_used_breakdown={},
                    cost_model_source_breakdown={},
                    cost_model_provider_breakdown={},
                )

            breakdowns = team_breakdowns[team_id]

            # Each row column (1-7) is a Map(String, UInt64)
            _merge_map_breakdowns(breakdowns.model_breakdown, row[1] or {})
            _merge_map_breakdowns(breakdowns.provider_breakdown, row[2] or {})
            _merge_map_breakdowns(breakdowns.framework_breakdown, row[3] or {})
            _merge_map_breakdowns(breakdowns.library_breakdown, row[4] or {})
            _merge_map_breakdowns(breakdowns.cost_model_used_breakdown, row[5] or {})
            _merge_map_breakdowns(breakdowns.cost_model_source_breakdown, row[6] or {})
            _merge_map_breakdowns(breakdowns.cost_model_provider_breakdown, row[7] or {})

    # Post-process to filter out empty keys
    for _team_id, breakdowns in team_breakdowns.items():
        breakdowns.model_breakdown = _filter_breakdown(breakdowns.model_breakdown)
        breakdowns.provider_breakdown = _filter_breakdown(breakdowns.provider_breakdown)
        breakdowns.framework_breakdown = _filter_breakdown(breakdowns.framework_breakdown, allow_empty=True)
        breakdowns.library_breakdown = _filter_breakdown(breakdowns.library_breakdown)
        breakdowns.cost_model_used_breakdown = _filter_breakdown(breakdowns.cost_model_used_breakdown)
        breakdowns.cost_model_source_breakdown = _filter_breakdown(breakdowns.cost_model_source_breakdown)
        breakdowns.cost_model_provider_breakdown = _filter_breakdown(breakdowns.cost_model_provider_breakdown)

    return team_breakdowns


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_all_ai_dimension_breakdowns(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[int, TeamDimensionBreakdowns]:
    """
    Get all dimension breakdowns (model, provider, framework, etc.) in a single query.

    Uses ClickHouse's sumMap() to aggregate dimension values efficiently.

    Returns:
        dict mapping team_id to TeamDimensionBreakdowns dataclass
    """

    lib_expression, _ = get_property_string_expr("events", "$lib", "'$lib'", "properties")

    query_template = f"""
        SELECT
            team_id,
            sumMap(map(properties_group_ai['$ai_model'], toUInt64(1))) as model_breakdown,
            sumMap(map(properties_group_ai['$ai_provider'], toUInt64(1))) as provider_breakdown,
            sumMap(map(properties_group_ai['$ai_framework'], toUInt64(1))) as framework_breakdown,
            sumMap(map({lib_expression}, toUInt64(1))) as library_breakdown,
            sumMap(map(properties_group_ai['$ai_model_cost_used'], toUInt64(1))) as cost_model_used_breakdown,
            sumMap(map(properties_group_ai['$ai_cost_model_source'], toUInt64(1))) as cost_model_source_breakdown,
            sumMap(map(properties_group_ai['$ai_cost_model_provider'], toUInt64(1))) as cost_model_provider_breakdown
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    return _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_breakdown_results,
        team_ids=team_ids,
        query_name="Get AI dimension breakdowns",
    )


# Celery task configuration
LLM_ANALYTICS_USAGE_REPORT_TASK_KWARGS = {
    "queue": CeleryQueue.USAGE_REPORTS.value,
    "ignore_result": True,
    "acks_late": True,
    "reject_on_worker_lost": True,
    "autoretry_for": (Exception,),
    "retry_backoff": 300,  # 5min
    "retry_backoff_max": 1800,  # 30min
    "expires": 14400,  # 4h
}


def _get_all_llm_analytics_reports(
    period_start: datetime,
    period_end: datetime,
) -> dict[str, dict[str, Any]]:
    """
    Gather all LLM Analytics usage data for all organizations.

    This function has been optimized to use only 2 queries instead of 44+:
    - 1 query to get team_ids with AI events
    - 1 combined query for all metrics (event counts, costs, tokens)
    - 1 combined query for all dimension breakdowns (using Maps)

    Returns:
        dict mapping organization_id to usage data
    """
    logger.info("Querying LLM Analytics usage data")

    # Phase 1: Get all team_ids with AI events (fast query)
    team_ids = get_teams_with_ai_events(period_start, period_end)

    if not team_ids:
        logger.info("No teams with AI events found")
        return {}

    logger.info(f"Found {len(team_ids)} teams with AI events")

    # Phase 2: Get all metrics in a single combined query
    logger.info("Querying all AI metrics")
    all_metrics = get_all_ai_metrics(period_start, period_end, team_ids)
    logger.info(f"Retrieved metrics for {len(all_metrics)} teams")

    # Phase 3: Get all dimension breakdowns in a single combined query
    logger.info("Querying all AI dimension breakdowns")
    all_breakdowns = get_all_ai_dimension_breakdowns(period_start, period_end, team_ids)
    logger.info(f"Retrieved breakdowns for {len(all_breakdowns)} teams")

    # Get team to organization mapping
    teams = Team.objects.filter(id__in=team_ids).select_related("organization")
    team_to_org: dict[int, str] = {team.id: str(team.organization_id) for team in teams}
    org_id_to_name: dict[str, str] = {str(team.organization_id): team.organization.name for team in teams}

    # Aggregate by organization
    org_reports: dict[str, dict[str, Any]] = {}

    for team_id, org_id in team_to_org.items():
        if org_id not in org_reports:
            org_reports[org_id] = {
                "organization_id": org_id,
                "organization_name": org_id_to_name.get(org_id, ""),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "ai_generation_count": 0,
                "ai_embedding_count": 0,
                "ai_span_count": 0,
                "ai_trace_count": 0,
                "ai_metric_count": 0,
                "ai_feedback_count": 0,
                "ai_evaluation_count": 0,
                "total_ai_cost_usd": 0.0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "request_cost_usd": 0.0,
                "web_search_cost_usd": 0.0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_reasoning_tokens": 0,
                "total_cache_read_tokens": 0,
                "total_cache_creation_tokens": 0,
                "model_breakdown": {},
                "provider_breakdown": {},
                "framework_breakdown": {},
                "library_breakdown": {},
                "cost_model_used_breakdown": {},
                "cost_model_source_breakdown": {},
                "cost_model_provider_breakdown": {},
            }

        report = org_reports[org_id]

        # Add metrics from TeamMetrics dataclass
        metrics = all_metrics.get(team_id)

        if metrics:
            report["ai_generation_count"] += metrics.ai_generation_count
            report["ai_embedding_count"] += metrics.ai_embedding_count
            report["ai_span_count"] += metrics.ai_span_count
            report["ai_trace_count"] += metrics.ai_trace_count
            report["ai_metric_count"] += metrics.ai_metric_count
            report["ai_feedback_count"] += metrics.ai_feedback_count
            report["ai_evaluation_count"] += metrics.ai_evaluation_count

            report["total_ai_cost_usd"] += metrics.total_cost
            report["input_cost_usd"] += metrics.input_cost
            report["output_cost_usd"] += metrics.output_cost
            report["request_cost_usd"] += metrics.request_cost
            report["web_search_cost_usd"] += metrics.web_search_cost

            report["total_prompt_tokens"] += metrics.prompt_tokens
            report["total_completion_tokens"] += metrics.completion_tokens
            report["total_tokens"] += metrics.total_tokens
            report["total_reasoning_tokens"] += metrics.reasoning_tokens
            report["total_cache_read_tokens"] += metrics.cache_read_tokens
            report["total_cache_creation_tokens"] += metrics.cache_creation_tokens

        # Add dimension breakdowns from TeamDimensionBreakdowns dataclass
        breakdowns = all_breakdowns.get(team_id)

        if breakdowns:
            for value, count in breakdowns.model_breakdown.items():
                report["model_breakdown"][value] = report["model_breakdown"].get(value, 0) + count

            for value, count in breakdowns.provider_breakdown.items():
                report["provider_breakdown"][value] = report["provider_breakdown"].get(value, 0) + count

            for value, count in breakdowns.framework_breakdown.items():
                report["framework_breakdown"][value] = report["framework_breakdown"].get(value, 0) + count

            for value, count in breakdowns.library_breakdown.items():
                report["library_breakdown"][value] = report["library_breakdown"].get(value, 0) + count

            for value, count in breakdowns.cost_model_used_breakdown.items():
                report["cost_model_used_breakdown"][value] = report["cost_model_used_breakdown"].get(value, 0) + count

            for value, count in breakdowns.cost_model_source_breakdown.items():
                report["cost_model_source_breakdown"][value] = (
                    report["cost_model_source_breakdown"].get(value, 0) + count
                )

            for value, count in breakdowns.cost_model_provider_breakdown.items():
                report["cost_model_provider_breakdown"][value] = (
                    report["cost_model_provider_breakdown"].get(value, 0) + count
                )

    logger.info(f"Generated LLM Analytics reports for {len(org_reports)} organizations")
    return org_reports


@shared_task(**LLM_ANALYTICS_USAGE_REPORT_TASK_KWARGS, max_retries=3)
def capture_llm_analytics_report(
    *,
    organization_id: str | None = None,
    report_dict: dict[str, Any],
    at_date: str | None = None,
) -> None:
    """
    Capture LLM Analytics usage report event for a specific organization.

    Args:
        organization_id: The organization ID
        report_dict: The usage report data
        at_date: ISO format timestamp for the report
    """
    if not organization_id:
        raise ValueError("organization_id must be provided")

    try:
        pha_client = get_ph_client()

        capture_event(
            pha_client=pha_client,
            name="llm analytics usage",
            organization_id=organization_id,
            properties=report_dict,
            timestamp=at_date,
        )
        logger.info(f"Captured LLM Analytics usage report for organization {organization_id}")
    except Exception as err:
        logger.exception(
            f"LLM Analytics usage report sent to PostHog for organization {organization_id} failed: {str(err)}",
        )

        try:
            pha_client = get_ph_client()
            capture_event(
                pha_client=pha_client,
                name="llm analytics usage report failure",
                organization_id=organization_id,
                properties={"error": str(err)},
            )
        except Exception as capture_err:
            logger.exception(f"Failed to capture error event: {capture_err}")

        raise


@shared_task(**LLM_ANALYTICS_USAGE_REPORT_TASK_KWARGS, max_retries=3)
def send_llm_analytics_usage_reports(
    dry_run: bool = False,
    at: str | None = None,
    organization_ids: list[str] | None = None,
) -> None:
    """
    Main task to send LLM Analytics usage reports for all organizations.

    Args:
        dry_run: If True, don't actually send reports
        at: ISO format date to run the report for (defaults to previous day)
        organization_ids: Optional list of specific organization IDs to report on
    """
    import posthoganalytics

    # Check if reports are disabled
    are_usage_reports_disabled = posthoganalytics.feature_enabled(
        "llm-analytics-disable-usage-reports", "internal_billing_events"
    )

    if are_usage_reports_disabled:
        posthoganalytics.capture_exception(Exception(f"LLM Analytics usage reports are disabled for {at}"))
        return

    at_date = parser.parse(at) if at else None
    period = get_previous_day(at=at_date)
    period_start, period_end = period

    if organization_ids:
        logger.info(
            "Sending LLM Analytics usage reports for specific organizations",
            org_count=len(organization_ids),
            organization_ids=organization_ids,
        )

    logger.info("Gathering LLM Analytics usage data")
    query_time_start = datetime.now(UTC)

    org_reports = _get_all_llm_analytics_reports(period_start, period_end)

    if organization_ids:
        original_count = len(org_reports)
        org_reports = {org_id: report for org_id, report in org_reports.items() if org_id in organization_ids}
        filtered_count = len(org_reports)
        missing_orgs = set(organization_ids) - set(org_reports.keys())

        logger.info(
            f"Filtered LLM Analytics org reports from {original_count} to {filtered_count} organizations",
            requested_org_count=len(organization_ids),
            found_org_count=filtered_count,
            missing_orgs=missing_orgs or None,
        )

    query_time_duration = (datetime.now(UTC) - query_time_start).total_seconds()
    logger.info(f"Found {len(org_reports)} LLM Analytics org reports. It took {query_time_duration} seconds.")

    if dry_run:
        logger.info("Dry run - not sending reports")
        return

    total_orgs = len(org_reports)
    total_orgs_sent = 0

    logger.info("Sending LLM Analytics usage reports")

    at_date_str = at_date.isoformat() if at_date else None

    for org_id, report in org_reports.items():
        try:
            capture_llm_analytics_report.delay(
                organization_id=org_id,
                report_dict=report,
                at_date=at_date_str,
            )
            total_orgs_sent += 1

        except Exception as err:
            logger.exception(f"Failed to queue LLM Analytics report for organization {org_id}: {err}")
            capture_exception(err)

    logger.info(
        f"Queued {total_orgs_sent}/{total_orgs} LLM Analytics usage reports",
        total_orgs=total_orgs,
        total_orgs_sent=total_orgs_sent,
        region=get_instance_region(),
    )
