import logging
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
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed_log
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


def _execute_split_query(
    begin: datetime,
    end: datetime,
    query_template: str,
    params: dict,
    num_splits: int = 2,
    combine_results_func: Any | None = None,
    team_ids: list[int] | None = None,
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


def _combine_event_type_results(results_list: list) -> list[tuple[int, str, int]]:
    """
    Combine results from queries that return (team_id, event, count) tuples.

    Args:
        results_list: List of query results, each containing (team_id, event, count) tuples

    Returns:
        Combined list of (team_id, event, count) tuples
    """
    team_event_counts: dict[tuple[int, str], int] = {}

    # Combine all results
    for results in results_list:
        for row in results:
            try:
                team_id, event, count = row
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed row in event type results: {row}, error: {e}")
                continue

            key = (team_id, event)

            if key in team_event_counts:
                team_event_counts[key] += count
            else:
                team_event_counts[key] = count

    # Convert back to the expected format
    return [(team_id, event, count) for (team_id, event), count in team_event_counts.items()]


def _combine_multi_metric_results(results_list: list) -> list[tuple]:
    """
    Combine results from queries that return (team_id, metric1, metric2, ...) tuples.

    Args:
        results_list: List of query results

    Returns:
        Combined list of tuples with summed metrics
    """
    team_metrics: dict[int, list[float]] = {}

    # Combine all results
    for results in results_list:
        for row in results:
            if not row:
                logger.warning("Skipping empty row in multi metric results")
                continue

            team_id = row[0]
            metrics = row[1:]  # All metrics after team_id

            if team_id in team_metrics:
                existing = team_metrics[team_id]

                # Ensure we don't go out of bounds - extend if new row has more metrics
                if len(metrics) > len(existing):
                    existing.extend([0] * (len(metrics) - len(existing)))

                # Sum each metric
                for i, metric in enumerate(metrics):
                    existing[i] += metric or 0
            else:
                # Initialize with current metrics
                team_metrics[team_id] = [metric or 0 for metric in metrics]

    # Convert back to the expected format
    return [(team_id, *metrics) for team_id, metrics in team_metrics.items()]


def _combine_dimension_results(results_list: list) -> list[tuple[int, str, int]]:
    """
    Combine results from dimension breakdown queries that return (team_id, dimension_value, count) tuples.

    Args:
        results_list: List of query results

    Returns:
        Combined list of (team_id, dimension_value, count) tuples
    """
    team_dimension_counts: dict[tuple[int, str], int] = {}

    # Combine all results
    for results in results_list:
        for row in results:
            try:
                team_id, dimension_value, count = row
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed row in dimension results: {row}, error: {e}")
                continue

            key = (team_id, dimension_value)

            if key in team_dimension_counts:
                team_dimension_counts[key] += count
            else:
                team_dimension_counts[key] = count

    # Convert back to the expected format
    return [(team_id, dim_val, count) for (team_id, dim_val), count in team_dimension_counts.items()]


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

    results = sync_execute(
        query,
        {"ai_events": AI_EVENTS, "begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_LLM_ANALYTICS_SETTINGS,
    )

    return [row[0] for row in results]


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


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_event_counts_by_type(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, list[tuple[int, int]]]:
    """
    Get counts for each AI event type per team.

    Returns:
        dict mapping event type to list of (team_id, count) tuples
    """
    query_template = """
        SELECT team_id, event, COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id, event
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_event_type_results,
        team_ids=team_ids,
    )

    # Organize results by event type
    event_counts: dict[str, dict[int, int]] = {event: {} for event in AI_EVENTS}

    for team_id, event, count in results:
        if event in event_counts:
            event_counts[event][team_id] = count

    # Convert to list format
    return {event: list(counts.items()) for event, counts in event_counts.items()}


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_cost_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, list[tuple[int, float]]]:
    """
    Get AI cost metrics per team.

    Returns:
        dict with keys: 'total_cost', 'input_cost', 'output_cost'
        Each maps to list of (team_id, cost) tuples
    """
    query_template = """
        SELECT
            team_id,
            SUM(toFloat64OrNull(JSONExtractRaw(properties, '$ai_total_cost_usd'))) as total_cost,
            SUM(toFloat64OrNull(JSONExtractRaw(properties, '$ai_input_cost_usd'))) as input_cost,
            SUM(toFloat64OrNull(JSONExtractRaw(properties, '$ai_output_cost_usd'))) as output_cost
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_multi_metric_results,
        team_ids=team_ids,
    )

    total_cost: list[tuple[int, float]] = []
    input_cost: list[tuple[int, float]] = []
    output_cost: list[tuple[int, float]] = []

    for team_id, total, input_val, output_val in results:
        total_cost.append((team_id, total or 0.0))
        input_cost.append((team_id, input_val or 0.0))
        output_cost.append((team_id, output_val or 0.0))

    return {
        "total_cost": total_cost,
        "input_cost": input_cost,
        "output_cost": output_cost,
    }


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_additional_cost_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, list[tuple[int, float]]]:
    """
    Get additional AI cost metrics per team (request costs, web search costs).

    Returns:
        dict with keys: 'request_cost', 'web_search_cost'
        Each maps to list of (team_id, cost) tuples
    """
    query_template = """
        SELECT
            team_id,
            SUM(toFloat64OrNull(JSONExtractRaw(properties, '$ai_request_cost_usd'))) as request_cost,
            SUM(toFloat64OrNull(JSONExtractRaw(properties, '$ai_web_search_cost_usd'))) as web_search_cost
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_multi_metric_results,
        team_ids=team_ids,
    )

    request_cost: list[tuple[int, float]] = []
    web_search_cost: list[tuple[int, float]] = []

    for team_id, request, web_search in results:
        request_cost.append((team_id, request or 0.0))
        web_search_cost.append((team_id, web_search or 0.0))

    return {
        "request_cost": request_cost,
        "web_search_cost": web_search_cost,
    }


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_token_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, list[tuple[int, int]]]:
    """
    Get AI token metrics per team.

    Returns:
        dict with keys: 'prompt_tokens', 'completion_tokens', 'total_tokens'
        Each maps to list of (team_id, count) tuples
    """
    query_template = """
        SELECT
            team_id,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_input_tokens'))) as prompt_tokens,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_output_tokens'))) as completion_tokens,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_total_tokens'))) as total_tokens
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_multi_metric_results,
        team_ids=team_ids,
    )

    prompt_tokens: list[tuple[int, int]] = []
    completion_tokens: list[tuple[int, int]] = []
    total_tokens: list[tuple[int, int]] = []

    for team_id, prompt, completion, total in results:
        prompt_tokens.append((team_id, prompt or 0))
        completion_tokens.append((team_id, completion or 0))
        total_tokens.append((team_id, total or 0))

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_additional_token_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, list[tuple[int, int]]]:
    """
    Get additional AI token metrics per team (reasoning tokens, cache tokens).

    Returns:
        dict with keys: 'reasoning_tokens', 'cache_read_tokens', 'cache_creation_tokens'
        Each maps to list of (team_id, count) tuples
    """
    query_template = """
        SELECT
            team_id,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_reasoning_tokens'))) as reasoning_tokens,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_cache_read_input_tokens'))) as cache_read_tokens,
            SUM(toInt64OrNull(JSONExtractRaw(properties, '$ai_cache_creation_input_tokens'))) as cache_creation_tokens
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=3,
        combine_results_func=_combine_multi_metric_results,
        team_ids=team_ids,
    )

    reasoning_tokens: list[tuple[int, int]] = []
    cache_read_tokens: list[tuple[int, int]] = []
    cache_creation_tokens: list[tuple[int, int]] = []

    for team_id, reasoning, cache_read, cache_creation in results:
        reasoning_tokens.append((team_id, reasoning or 0))
        cache_read_tokens.append((team_id, cache_read or 0))
        cache_creation_tokens.append((team_id, cache_creation or 0))

    return {
        "reasoning_tokens": reasoning_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    }


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_dimension_breakdowns(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[str, dict[int, dict[str, int]]]:
    """
    Get dimension breakdowns (model, provider, framework, library) per team.

    Returns:
        dict with keys: 'model', 'provider', 'framework', 'library'
        Each maps to: {team_id: {dimension_value: count}}
    """
    # Query for model breakdown
    model_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_model') as model,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, model
    """
    model_results = _execute_split_query(
        begin,
        end,
        model_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for provider breakdown
    provider_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_provider') as provider,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, provider
    """
    provider_results = _execute_split_query(
        begin,
        end,
        provider_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for framework breakdown
    framework_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_framework') as framework,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, framework
    """
    framework_results = _execute_split_query(
        begin,
        end,
        framework_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for library breakdown
    library_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$lib') as library,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, library
    """
    library_results = _execute_split_query(
        begin,
        end,
        library_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for cost model used breakdown
    cost_model_used_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_model_cost_used') as cost_model_used,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, cost_model_used
    """
    cost_model_used_results = _execute_split_query(
        begin,
        end,
        cost_model_used_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for cost model source breakdown
    cost_model_source_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_cost_model_source') as cost_model_source,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, cost_model_source
    """
    cost_model_source_results = _execute_split_query(
        begin,
        end,
        cost_model_source_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Query for cost model provider breakdown
    cost_model_provider_query_template = """
        SELECT
            team_id,
            JSONExtractString(properties, '$ai_cost_model_provider') as cost_model_provider,
            COUNT() as count
        FROM events
        WHERE team_id IN %(team_ids)s
            AND event IN %(ai_events)s
            AND timestamp >= %(begin)s
            AND timestamp < %(end)s
        GROUP BY team_id, cost_model_provider
    """
    cost_model_provider_results = _execute_split_query(
        begin,
        end,
        cost_model_provider_query_template,
        {"ai_events": AI_EVENTS},
        num_splits=4,
        combine_results_func=_combine_dimension_results,
        team_ids=team_ids,
    )

    # Organize results into nested dicts
    model_breakdown: dict[int, dict[str, int]] = {}

    for team_id, model, count in model_results:
        # Filter out empty or whitespace-only model values
        if not model or not model.strip():
            continue

        if team_id not in model_breakdown:
            model_breakdown[team_id] = {}

        model_breakdown[team_id][model] = count

    provider_breakdown: dict[int, dict[str, int]] = {}

    for team_id, provider, count in provider_results:
        # Filter out empty or whitespace-only provider values
        if not provider or not provider.strip():
            continue

        if team_id not in provider_breakdown:
            provider_breakdown[team_id] = {}

        provider_breakdown[team_id][provider] = count

    framework_breakdown: dict[int, dict[str, int]] = {}

    for team_id, framework, count in framework_results:
        if team_id not in framework_breakdown:
            framework_breakdown[team_id] = {}

        # Use "none" for empty/null/whitespace-only frameworks
        framework_key = framework.strip() if framework and framework.strip() else "none"
        framework_breakdown[team_id][framework_key] = count

    library_breakdown: dict[int, dict[str, int]] = {}

    for team_id, library, count in library_results:
        # Filter out empty or whitespace-only library values
        if not library or not library.strip():
            continue

        if team_id not in library_breakdown:
            library_breakdown[team_id] = {}

        library_breakdown[team_id][library] = count

    cost_model_used_breakdown: dict[int, dict[str, int]] = {}

    for team_id, cost_model_used, count in cost_model_used_results:
        # Filter out empty or whitespace-only values
        if not cost_model_used or not cost_model_used.strip():
            continue

        if team_id not in cost_model_used_breakdown:
            cost_model_used_breakdown[team_id] = {}

        cost_model_used_breakdown[team_id][cost_model_used] = count

    cost_model_source_breakdown: dict[int, dict[str, int]] = {}

    for team_id, cost_model_source, count in cost_model_source_results:
        # Filter out empty or whitespace-only values
        if not cost_model_source or not cost_model_source.strip():
            continue

        if team_id not in cost_model_source_breakdown:
            cost_model_source_breakdown[team_id] = {}

        cost_model_source_breakdown[team_id][cost_model_source] = count

    cost_model_provider_breakdown: dict[int, dict[str, int]] = {}

    for team_id, cost_model_provider, count in cost_model_provider_results:
        # Filter out empty or whitespace-only values
        if not cost_model_provider or not cost_model_provider.strip():
            continue

        if team_id not in cost_model_provider_breakdown:
            cost_model_provider_breakdown[team_id] = {}

        cost_model_provider_breakdown[team_id][cost_model_provider] = count

    return {
        "model": model_breakdown,
        "provider": provider_breakdown,
        "framework": framework_breakdown,
        "library": library_breakdown,
        "cost_model_used": cost_model_used_breakdown,
        "cost_model_source": cost_model_source_breakdown,
        "cost_model_provider": cost_model_provider_breakdown,
    }


def _get_all_llm_analytics_reports(
    period_start: datetime,
    period_end: datetime,
) -> dict[str, dict[str, Any]]:
    """
    Gather all LLM Analytics usage data for all organizations.

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

    # Phase 2: Get detailed metrics filtered by team_ids (uses primary key index)
    event_counts_by_type = get_ai_event_counts_by_type(period_start, period_end, team_ids)
    cost_metrics = get_ai_cost_metrics(period_start, period_end, team_ids)
    additional_cost_metrics = get_ai_additional_cost_metrics(period_start, period_end, team_ids)
    token_metrics = get_ai_token_metrics(period_start, period_end, team_ids)
    additional_token_metrics = get_ai_additional_token_metrics(period_start, period_end, team_ids)
    dimension_breakdowns = get_ai_dimension_breakdowns(period_start, period_end, team_ids)

    # Convert to dict for easier lookup
    event_counts_dicts = {event: dict(counts) for event, counts in event_counts_by_type.items()}
    cost_dicts = {key: dict(values) for key, values in cost_metrics.items()}
    additional_cost_dicts = {key: dict(values) for key, values in additional_cost_metrics.items()}
    token_dicts = {key: dict(values) for key, values in token_metrics.items()}
    additional_token_dicts = {key: dict(values) for key, values in additional_token_metrics.items()}

    all_teams_with_ai = set(team_ids)

    # Get team to organization mapping
    teams = Team.objects.filter(id__in=all_teams_with_ai).select_related("organization")
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

        # Add event counts by type
        report["ai_generation_count"] += event_counts_dicts.get("$ai_generation", {}).get(team_id, 0)
        report["ai_embedding_count"] += event_counts_dicts.get("$ai_embedding", {}).get(team_id, 0)
        report["ai_span_count"] += event_counts_dicts.get("$ai_span", {}).get(team_id, 0)
        report["ai_trace_count"] += event_counts_dicts.get("$ai_trace", {}).get(team_id, 0)
        report["ai_metric_count"] += event_counts_dicts.get("$ai_metric", {}).get(team_id, 0)
        report["ai_feedback_count"] += event_counts_dicts.get("$ai_feedback", {}).get(team_id, 0)
        report["ai_evaluation_count"] += event_counts_dicts.get("$ai_evaluation", {}).get(team_id, 0)

        # Add cost metrics
        report["total_ai_cost_usd"] += cost_dicts.get("total_cost", {}).get(team_id, 0.0)
        report["input_cost_usd"] += cost_dicts.get("input_cost", {}).get(team_id, 0.0)
        report["output_cost_usd"] += cost_dicts.get("output_cost", {}).get(team_id, 0.0)
        report["request_cost_usd"] += additional_cost_dicts.get("request_cost", {}).get(team_id, 0.0)
        report["web_search_cost_usd"] += additional_cost_dicts.get("web_search_cost", {}).get(team_id, 0.0)

        # Add token metrics
        report["total_prompt_tokens"] += token_dicts.get("prompt_tokens", {}).get(team_id, 0)
        report["total_completion_tokens"] += token_dicts.get("completion_tokens", {}).get(team_id, 0)
        report["total_tokens"] += token_dicts.get("total_tokens", {}).get(team_id, 0)
        report["total_reasoning_tokens"] += additional_token_dicts.get("reasoning_tokens", {}).get(team_id, 0)
        report["total_cache_read_tokens"] += additional_token_dicts.get("cache_read_tokens", {}).get(team_id, 0)
        report["total_cache_creation_tokens"] += additional_token_dicts.get("cache_creation_tokens", {}).get(team_id, 0)

        # Merge dimension breakdowns
        for dimension in [
            "model",
            "provider",
            "framework",
            "library",
            "cost_model_used",
            "cost_model_source",
            "cost_model_provider",
        ]:
            breakdown_key = f"{dimension}_breakdown"
            team_breakdown = dimension_breakdowns[dimension].get(team_id, {})

            for value, count in team_breakdown.items():
                if value not in report[breakdown_key]:
                    report[breakdown_key][value] = 0

                report[breakdown_key][value] += count

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
