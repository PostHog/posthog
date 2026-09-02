from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from cachetools import cached
from celery import Task, shared_task
from dateutil import parser
from posthoganalytics.client import Client as PostHogClient
from retry import retry

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed_log
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.property.util import get_property_string_expr
from posthog.models.team.team import Team
from posthog.ph_client import PH_US_API_KEY
from posthog.schema_enums import AIEventType
from posthog.tasks.report_utils import capture_event
from posthog.tasks.utils import CeleryQueue
from posthog.utils import DayRange, get_instance_region, get_previous_day

logger = structlog.get_logger(__name__)


@cached(cache={})
def get_ph_client() -> PostHogClient:
    """Get a PostHog client instance for capturing events.

    Shares `PH_US_API_KEY` with `internal_reporting_team_id`, which resolves the team the
    already-reported lookup reads. A separate literal here could drift from that key, and the lookup
    would then resolve no team, report that it cannot verify, and emit without checking.
    """
    return PostHogClient(PH_US_API_KEY, sync_mode=True)


AI_EVENTS = [event.value for event in AIEventType]
LLM_PROMPT_FETCHED_EVENT = "$llm_prompt_fetched"

# The emitted report event. Shared by the emission and the already-reported lookup so the two
# cannot drift: a lookup reading a different name would find nothing and silently allow duplicates.
AI_OBSERVABILITY_USAGE_EVENT = "llm analytics usage"

AI_OBSERVABILITY_REPORT_TRIGGER_EVENTS = [*AI_EVENTS, LLM_PROMPT_FETCHED_EVENT]

# Restricted to customer-emitted events that produce data downstream LLM analytics workflows can act on:
# excludes server-side artifacts like summaries, reports, and clusters, and prompt-management events that
# don't generate traces.
LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS: list[str] = [
    AIEventType.FIELD_AI_GENERATION.value,
    AIEventType.FIELD_AI_EMBEDDING.value,
    AIEventType.FIELD_AI_SPAN.value,
    AIEventType.FIELD_AI_TRACE.value,
    AIEventType.FIELD_AI_METRIC.value,
    AIEventType.FIELD_AI_FEEDBACK.value,
    AIEventType.FIELD_AI_EVALUATION.value,
]

# ClickHouse query settings for AI observability queries
CH_AI_OBSERVABILITY_SETTINGS = {
    "max_execution_time": 5 * 60,  # 5 minutes
}

# Query retry configuration
QUERY_RETRIES = 3
QUERY_RETRY_DELAY = 1
QUERY_RETRY_BACKOFF = 2

# How long a queued report message may still be in flight before Celery discards it. The dispatch
# claim reuses this, so the two cannot disagree about how long a run may still be emitting.
USAGE_REPORT_MESSAGE_EXPIRY_SECONDS = 4 * 60 * 60

# Celery task ID for query attribution
CELERY_TASK_ID = "posthog.tasks.llm_analytics_usage_report.send_llm_analytics_usage_reports"


def _ai_property_expr(property_name: str, use_new_events_schema: bool) -> str:
    """A String read of an AI event property: the `properties_group_ai` map on the legacy schema.

    events_json has no property-group columns, so read the property from the JSON `properties`
    there instead, coalescing NULL to '' to keep the map-read semantics (missing key reads '').
    """
    if not use_new_events_schema:
        return f"properties_group_ai['{property_name}']"
    expr, is_denormalized = get_property_string_expr(
        "events", property_name, f"'{property_name}'", "properties", use_new_events_schema=True
    )
    return expr if is_denormalized else f"ifNull({expr}, '')"


# Mutable by design: the split-query combiner accumulates into one instance per team.
@dataclass(frozen=False)
class TeamMetrics:
    """All metrics for a single team from the combined query."""

    team_id: int

    # Event counts
    ai_generation_count: int = 0
    ai_embedding_count: int = 0
    ai_span_count: int = 0
    ai_trace_event_count: int = 0
    ai_metric_count: int = 0
    ai_feedback_count: int = 0
    ai_evaluation_count: int = 0
    ai_is_error_count: int = 0
    ai_llm_judge_evaluation_count: int = 0
    ai_hog_evaluation_count: int = 0
    ai_sentiment_evaluation_count: int = 0
    ai_trace_summary_count: int = 0
    ai_generation_summary_count: int = 0
    ai_trace_clusters_count: int = 0
    ai_generation_clusters_count: int = 0

    # Cost metrics
    total_cost: float = 0.0
    total_cost_count: int = 0
    total_cost_negative_count: int = 0
    total_cost_zero_count: int = 0
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
            feature=Feature.QUERY,
            kind="celery",
            id=CELERY_TASK_ID,
            name=query_name,
            workload=Workload.OFFLINE.value,
        ):
            split_result = sync_execute(
                query_template,
                split_params,
                workload=Workload.OFFLINE,
                settings=CH_AI_OBSERVABILITY_SETTINGS,
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
def get_teams_with_ai_events(
    begin: datetime,
    end: datetime,
    trigger_events: list[str],
) -> list[int]:
    """
    Get all team_ids that have at least one AI observability trigger event in the period.

    This is a fast query that returns only distinct team_ids, allowing subsequent
    queries to filter by team_id and use the primary key index efficiently.
    """
    query = f"""
        SELECT DISTINCT team_id
        FROM {events_read_table(use_new_events_schema(None))}
        WHERE event IN %(ai_observability_report_trigger_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
    """

    with tags_context(
        product=Product.LLM_ANALYTICS,
        feature=Feature.QUERY,
        kind="celery",
        id=CELERY_TASK_ID,
        name="Get teams with AI observability trigger events",
        workload=Workload.OFFLINE.value,
    ):
        results = sync_execute(
            query,
            {
                "ai_observability_report_trigger_events": trigger_events,
                "begin": begin,
                "end": end,
            },
            workload=Workload.OFFLINE,
            settings=CH_AI_OBSERVABILITY_SETTINGS,
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

            # Event counts (indices 1-11)
            metrics.ai_generation_count += row[1] or 0
            metrics.ai_embedding_count += row[2] or 0
            metrics.ai_span_count += row[3] or 0
            metrics.ai_trace_event_count += row[4] or 0
            metrics.ai_metric_count += row[5] or 0
            metrics.ai_feedback_count += row[6] or 0
            metrics.ai_evaluation_count += row[7] or 0
            metrics.ai_trace_summary_count += row[8] or 0
            metrics.ai_generation_summary_count += row[9] or 0
            metrics.ai_trace_clusters_count += row[10] or 0
            metrics.ai_generation_clusters_count += row[11] or 0

            # Cost metrics (indices 12-16)
            metrics.total_cost += row[12] or 0.0
            metrics.input_cost += row[13] or 0.0
            metrics.output_cost += row[14] or 0.0
            metrics.request_cost += row[15] or 0.0
            metrics.web_search_cost += row[16] or 0.0

            # Token metrics (indices 17-22)
            metrics.prompt_tokens += row[17] or 0
            metrics.completion_tokens += row[18] or 0
            metrics.total_tokens += row[19] or 0
            metrics.reasoning_tokens += row[20] or 0
            metrics.cache_read_tokens += row[21] or 0
            metrics.cache_creation_tokens += row[22] or 0

            # Cost anomaly counts (indices 23-25)
            metrics.total_cost_count += row[23] or 0
            metrics.total_cost_negative_count += row[24] or 0
            metrics.total_cost_zero_count += row[25] or 0

            # Error count (index 26)
            metrics.ai_is_error_count += row[26] or 0

            # Evaluation runtime counts (indices 27-29)
            metrics.ai_llm_judge_evaluation_count += row[27] or 0
            metrics.ai_hog_evaluation_count += row[28] or 0
            metrics.ai_sentiment_evaluation_count += row[29] or 0

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
    use_new = use_new_events_schema(None)

    def prop(name: str) -> str:
        return _ai_property_expr(name, use_new)

    query_template = f"""
        SELECT
            team_id,
            -- Event counts by type
            countIf(event = '$ai_generation') as ai_generation_count,
            countIf(event = '$ai_embedding') as ai_embedding_count,
            countIf(event = '$ai_span') as ai_span_count,
            countIf(event = '$ai_trace') as ai_trace_event_count,
            countIf(event = '$ai_metric') as ai_metric_count,
            countIf(event = '$ai_feedback') as ai_feedback_count,
            countIf(event = '$ai_evaluation') as ai_evaluation_count,
            countIf(event = '$ai_trace_summary') as ai_trace_summary_count,
            countIf(event = '$ai_generation_summary') as ai_generation_summary_count,
            countIf(event = '$ai_trace_clusters') as ai_trace_clusters_count,
            countIf(event = '$ai_generation_clusters') as ai_generation_clusters_count,
            -- Cost metrics
            SUM(toFloat64OrNull({prop("$ai_total_cost_usd")})) as total_cost,
            SUM(toFloat64OrNull({prop("$ai_input_cost_usd")})) as input_cost,
            SUM(toFloat64OrNull({prop("$ai_output_cost_usd")})) as output_cost,
            SUM(toFloat64OrNull({prop("$ai_request_cost_usd")})) as request_cost,
            SUM(toFloat64OrNull({prop("$ai_web_search_cost_usd")})) as web_search_cost,
            -- Token metrics
            SUM(toInt64OrNull({prop("$ai_input_tokens")})) as prompt_tokens,
            SUM(toInt64OrNull({prop("$ai_output_tokens")})) as completion_tokens,
            SUM(toInt64OrNull({prop("$ai_total_tokens")})) as total_tokens,
            SUM(toInt64OrNull({prop("$ai_reasoning_tokens")})) as reasoning_tokens,
            SUM(toInt64OrNull({prop("$ai_cache_read_input_tokens")})) as cache_read_tokens,
            SUM(toInt64OrNull({prop("$ai_cache_creation_input_tokens")})) as cache_creation_tokens,
            -- Cost anomaly counts
            countIf(toFloat64OrNull({prop("$ai_total_cost_usd")}) IS NOT NULL) as total_cost_count,
            countIf(toFloat64OrNull({prop("$ai_total_cost_usd")}) < 0) as total_cost_negative_count,
            countIf(toFloat64OrNull({prop("$ai_total_cost_usd")}) = 0) as total_cost_zero_count,
            -- Error count
            countIf({prop("$ai_is_error")} = 'true') as ai_is_error_count,
            -- Evaluation counts
            countIf(event = '$ai_evaluation' AND {prop("$ai_evaluation_runtime")} = 'llm_judge') as ai_llm_judge_evaluation_count,
            countIf(event = '$ai_evaluation' AND {prop("$ai_evaluation_runtime")} = 'hog') as ai_hog_evaluation_count,
            countIf(event = '$ai_evaluation' AND {prop("$ai_evaluation_runtime")} = 'sentiment') as ai_sentiment_evaluation_count
        FROM {events_read_table(use_new)}
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


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_ai_trace_counts(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[int, int]:
    """
    Get the number of distinct traces per team.

    Counts distinct `$ai_trace_id` across every AI event rather than `$ai_trace` events, because
    emitting a root `$ai_trace` event is optional: several SDK integrations group generations under a
    trace id without ever sending the root event. Counting the root event makes those teams look like
    they stopped producing traces when only their instrumentation shape changed.

    Returns:
        dict mapping team_id to distinct trace count
    """
    use_new = use_new_events_schema(None)
    trace_id = _ai_property_expr("$ai_trace_id", use_new)

    query_template = f"""
        SELECT
            team_id,
            uniqIf({trace_id}, {trace_id} != '') as ai_trace_count
        FROM {events_read_table(use_new)}
        WHERE team_id IN %(team_ids)s
          AND event IN %(ai_events)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    # Deliberately unsplit: the split combiners sum per team, which would count a trace once per time
    # split it spans. `uniq` holds a fixed-size sketch per team, so one query over the whole period
    # stays within the memory budget the splits exist to protect.
    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"ai_events": AI_EVENTS},
        num_splits=1,
        team_ids=team_ids,
        query_name="Get AI trace counts",
    )

    return dict(results)


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_llm_prompt_fetched_counts(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[int, int]:
    """
    Get LLM prompt fetched event counts per team.

    Returns:
        dict mapping team_id to prompt fetched count
    """
    query_template = f"""
        SELECT
            team_id,
            count() as llm_prompt_fetched_count
        FROM {events_read_table(use_new_events_schema(None))}
        WHERE team_id IN %(team_ids)s
          AND event = %(llm_prompt_fetched_event)s
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id
    """

    results = _execute_split_query(
        begin,
        end,
        query_template,
        {"llm_prompt_fetched_event": LLM_PROMPT_FETCHED_EVENT},
        num_splits=2,
        team_ids=team_ids,
        query_name="Get LLM prompt fetched counts",
    )

    return dict(results)


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

    use_new = use_new_events_schema(None)
    lib_expression, _ = get_property_string_expr(
        "events", "$lib", "'$lib'", "properties", use_new_events_schema=use_new
    )

    def prop(name: str) -> str:
        return _ai_property_expr(name, use_new)

    query_template = f"""
        SELECT
            team_id,
            sumMap(map({prop("$ai_model")}, toUInt64(1))) as model_breakdown,
            sumMap(map({prop("$ai_provider")}, toUInt64(1))) as provider_breakdown,
            sumMap(map({prop("$ai_framework")}, toUInt64(1))) as framework_breakdown,
            sumMap(map({lib_expression}, toUInt64(1))) as library_breakdown,
            sumMap(map({prop("$ai_model_cost_used")}, toUInt64(1))) as cost_model_used_breakdown,
            sumMap(map({prop("$ai_cost_model_source")}, toUInt64(1))) as cost_model_source_breakdown,
            sumMap(map({prop("$ai_cost_model_provider")}, toUInt64(1))) as cost_model_provider_breakdown
        FROM {events_read_table(use_new)}
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


@dataclass
class TeamLLMSurveyMetrics:
    """Survey metrics for a single team linked to LLM traces."""

    active_survey_count: int = 0
    response_count: int = 0


def _combine_llm_survey_results(results_list: list) -> dict[int, TeamLLMSurveyMetrics]:
    """
    Combine results from split queries that return (team_id, survey_id, response_count) rows.

    Deduplicates survey IDs across splits and sums response counts.
    """
    team_survey_responses: dict[int, dict[str, int]] = {}

    for results in results_list:
        for team_id, survey_id, response_count in results:
            if team_id not in team_survey_responses:
                team_survey_responses[team_id] = {}
            surveys = team_survey_responses[team_id]
            surveys[survey_id] = surveys.get(survey_id, 0) + (response_count or 0)

    return {
        team_id: TeamLLMSurveyMetrics(
            active_survey_count=len(surveys),
            response_count=sum(surveys.values()),
        )
        for team_id, surveys in team_survey_responses.items()
    }


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_llm_feedback_survey_metrics(
    begin: datetime,
    end: datetime,
    team_ids: list[int],
) -> dict[int, TeamLLMSurveyMetrics]:
    """
    Get LLM feedback survey metrics per team.

    Finds 'survey sent'/'survey shown' events with a $ai_trace_id property
    during the period and computes:
    - active_survey_count: distinct survey IDs seen (active surveys attached to traces)
    - response_count: number of 'survey sent' events (submitted responses)

    Groups by (team_id, survey_id) so the split query combiner can properly
    deduplicate survey IDs across time splits.

    Returns:
        dict mapping team_id to TeamLLMSurveyMetrics
    """
    use_new = use_new_events_schema(None)
    ai_trace_id_expr, _ = get_property_string_expr(
        "events", "$ai_trace_id", "'$ai_trace_id'", "properties", use_new_events_schema=use_new
    )
    survey_id_expr, _ = get_property_string_expr(
        "events", "$survey_id", "'$survey_id'", "properties", use_new_events_schema=use_new
    )

    query_template = f"""
        SELECT
            team_id,
            {survey_id_expr} as survey_id,
            countIf(event = 'survey sent') as response_count
        FROM {events_read_table(use_new)}
        WHERE team_id IN %(team_ids)s
          AND event IN ('survey sent', 'survey shown')
          AND {ai_trace_id_expr} != ''
          AND {survey_id_expr} != ''
          AND timestamp >= %(begin)s
          AND timestamp < %(end)s
        GROUP BY team_id, survey_id
    """

    return _execute_split_query(
        begin,
        end,
        query_template,
        {},
        num_splits=2,
        combine_results_func=_combine_llm_survey_results,
        team_ids=team_ids,
        query_name="Get LLM feedback survey metrics",
    )


# Every report is stamped this far after the start of the period it covers, whenever it is emitted.
# A backfill of an old period therefore lands next to that period rather than at the operator's wall
# clock, which is what lets the already-reported lookup bound its scan without missing a report.
REPORT_STAMP_OFFSET = timedelta(days=1)

# Bounds the scan for the already-reported lookup, which has to see every stamp a report for the
# period could carry. Derived from the stamp offset rather than set independently, so moving where
# reports are stamped cannot leave the lookup scanning a window that no longer contains them.
#
# The slack over the offset is deliberately far larger than the offset itself, because the two
# directions are not symmetric. A window that is too wide reads more rows, and reads them cheaply,
# since team_id, the timestamp range and the event name are all a prefix of the events table sort key.
# A window that is too narrow reads a report that exists as never emitted and emits a duplicate, which
# no consumer of these events can remove. The slack also covers reports emitted before stamping became
# deterministic, which carry their arrival time rather than a fixed offset.
REPORTED_LOOKUP_WINDOW = REPORT_STAMP_OFFSET + timedelta(days=89)

# A claim has to outlive the run that took it, otherwise it lapses while the first dispatch is still
# emitting and a second dispatch is admitted whose lookup cannot see the first one's events yet.
USAGE_REPORT_DISPATCH_LOCK_TIMEOUT_SECONDS = USAGE_REPORT_MESSAGE_EXPIRY_SECONDS


def usage_report_dispatch_lock_key(date: str) -> str:
    """Cache key claiming a report date.

    Keyed on the date alone, deliberately, even though it makes two disjoint `--org-ids` backfills of
    one date serialize. The admin button always dispatches a whole date, so a key that also covered
    the org scope would give the button and an org-scoped run different keys and let both through.
    """
    return f"ai-observability-usage-report-dispatch:{date}"


def internal_reporting_team_id() -> int | None:
    """The team whose events hold previously emitted reports, when this region has one.

    `get_ph_client` emits with the US project's token from every region, so reports only ever land in
    that one project and only a worker in the region hosting it can read them back. Everywhere else
    the token matches no team. Callers must read None as "cannot verify", never as "nothing emitted".
    """
    return Team.objects.filter(api_token=PH_US_API_KEY).values_list("id", flat=True).first()


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_organizations_already_reported(period_start: datetime, internal_team_id: int) -> set[str]:
    """Organization ids that already have a report covering `period_start`.

    Matched on the `period_start` report property rather than on the event timestamp, because the
    timestamp is a presentation choice that has already changed once, so deriving the period from it
    would break silently if it changed again. `organization_id` and `period_start` are read from
    `properties` rather than through `_ai_property_expr`: the `ai` property group only holds keys
    matching `$ai_%`, so a group read of either would always return empty and allow every duplicate.
    """
    use_new = use_new_events_schema(internal_team_id)
    org_id_expr, _ = get_property_string_expr(
        "events", "organization_id", "'organization_id'", "properties", use_new_events_schema=use_new
    )
    period_start_expr, _ = get_property_string_expr(
        "events", "period_start", "'period_start'", "properties", use_new_events_schema=use_new
    )

    query = f"""
        SELECT DISTINCT {org_id_expr} AS organization_id
        FROM {events_read_table(use_new)}
        WHERE team_id = %(team_id)s
          AND event = %(event)s
          AND timestamp >= %(window_start)s
          AND timestamp < %(window_end)s
          AND toDate(parseDateTimeBestEffortOrNull({period_start_expr})) = toDate(%(period_start)s)
          AND organization_id != ''
    """

    with tags_context(
        product=Product.LLM_ANALYTICS,
        feature=Feature.QUERY,
        kind="celery",
        id=CELERY_TASK_ID,
        name="Get organizations already reported",
        workload=Workload.OFFLINE.value,
    ):
        results = sync_execute(
            query,
            {
                "team_id": internal_team_id,
                "event": AI_OBSERVABILITY_USAGE_EVENT,
                "window_start": period_start,
                "window_end": period_start + REPORTED_LOOKUP_WINDOW,
                "period_start": period_start,
            },
            workload=Workload.OFFLINE,
            settings=CH_AI_OBSERVABILITY_SETTINGS,
        )

    return {row[0] for row in results}


def _get_organizations_to_skip(period_start: datetime) -> set[str]:
    """Organizations to leave out of this run because they already have a report for the period.

    Returns an empty set where this region cannot read previously emitted reports, which emits
    everything and matches the behaviour before the lookup existed. A lookup that fails for any other
    reason raises instead, and that is deliberate: the run then cannot tell whether the period already
    has reports, and emitting anyway would double count usage in every insight built on these events
    with no way to remove the duplicates. Raising lets Celery retry and, if the failure persists, give
    up having emitted nothing.

    Two limits are worth knowing, both of which want a durable per organization and period record to
    close properly. The evidence is an event in a project whose write token is public, so a forged
    event carrying an organization id and a period start suppresses that organization's real report for
    the period. And an emission is only visible here once ingested, so a run redelivered inside that
    lag reads the period as unreported.
    """
    internal_team_id = internal_reporting_team_id()
    if internal_team_id is None:
        logger.warning(
            "[AIO Usage Error] cannot check for already-emitted reports in this region, emitting without the check",
            period_start=period_start.isoformat(),
            event_source="ai_observability_usage_report",
        )
        return set()

    return get_organizations_already_reported(period_start, internal_team_id)


def _is_final_attempt(task: Task) -> bool:
    """Whether a failure now is permanent: a direct (synchronous) call never retries, and the
    last autoretry attempt runs with retries >= max_retries."""
    if task.request.called_directly:
        return True
    return task.max_retries is not None and task.request.retries >= task.max_retries


# Celery task configuration
AI_OBSERVABILITY_USAGE_REPORT_TASK_KWARGS = {
    "queue": CeleryQueue.USAGE_REPORTS.value,
    "ignore_result": True,
    "acks_late": True,
    "reject_on_worker_lost": True,
    "autoretry_for": (Exception,),
    "retry_backoff": 300,  # 5min
    "retry_backoff_max": 1800,  # 30min
    "expires": USAGE_REPORT_MESSAGE_EXPIRY_SECONDS,
}


def _get_all_ai_observability_reports(
    *,
    period: DayRange,
) -> dict[str, dict[str, Any]]:
    """
    Gather all AI observability usage data for all organizations.

    This function has been optimized to use a small number of queries instead of 44+:
    - 1 query to get team_ids with AI observability trigger events
    - 1 combined query for all metrics (event counts, costs, tokens)
    - 1 query for LLM prompt fetched counts
    - 1 combined query for all dimension breakdowns (using Maps)

    Returns:
        dict mapping organization_id to usage data
    """
    logger.info("Querying AI observability usage data")

    # Phase 1: Get all team_ids with report trigger events (fast query)
    try:
        team_ids = get_teams_with_ai_events(period.start, period.end, AI_OBSERVABILITY_REPORT_TRIGGER_EVENTS)
    except Exception:
        logger.warning(
            "[AIO Usage Error] teams query failed",
            phase="teams",
            event_source="ai_observability_usage_report",
            exc_info=True,
        )
        # Re-raise so Celery's autoretry_for=(Exception,) kicks in. Do not swallow.
        raise

    if not team_ids:
        logger.info("No teams with AI observability trigger events found")
        return {}

    logger.info(f"Found {len(team_ids)} teams with AI observability trigger events")

    # Phase 2: Get all metrics in a single combined query
    logger.info("Querying all AI metrics")
    try:
        all_metrics = get_all_ai_metrics(period.start, period.end, team_ids)
    except Exception:
        logger.warning(
            "[AIO Usage Error] metrics query failed",
            phase="metrics",
            event_source="ai_observability_usage_report",
            exc_info=True,
        )
        # Re-raise so Celery's autoretry_for=(Exception,) kicks in. Do not swallow.
        raise
    logger.info(f"Retrieved metrics for {len(all_metrics)} teams")

    # Phase 3: Get distinct trace counts
    logger.info("Querying AI trace counts")
    try:
        ai_trace_counts = get_ai_trace_counts(period.start, period.end, team_ids)
    except Exception:
        logger.warning(
            "[AIO Usage Error] trace counts query failed",
            phase="trace_counts",
            event_source="ai_observability_usage_report",
            exc_info=True,
        )
        # Re-raise so Celery's autoretry_for=(Exception,) kicks in. Do not swallow.
        raise
    logger.info(f"Retrieved trace counts for {len(ai_trace_counts)} teams")

    # Phase 4: Get LLM prompt fetched counts (best effort)
    llm_prompt_fetched_counts: dict[int, int] = {}
    try:
        logger.info("Querying LLM prompt fetched counts")
        llm_prompt_fetched_counts = get_llm_prompt_fetched_counts(period.start, period.end, team_ids)
        logger.info(f"Retrieved prompt fetched counts for {len(llm_prompt_fetched_counts)} teams")
    except Exception as err:
        logger.warning(
            "Failed to query LLM prompt fetched counts, continuing without prompt fetch metrics", exc_info=True
        )
        capture_exception(err)

    # Phase 5: Get all dimension breakdowns in a single combined query
    logger.info("Querying all AI dimension breakdowns")
    try:
        all_breakdowns = get_all_ai_dimension_breakdowns(period.start, period.end, team_ids)
    except Exception:
        logger.warning(
            "[AIO Usage Error] breakdowns query failed",
            phase="breakdowns",
            event_source="ai_observability_usage_report",
            exc_info=True,
        )
        # Re-raise so Celery's autoretry_for=(Exception,) kicks in. Do not swallow.
        raise
    logger.info(f"Retrieved breakdowns for {len(all_breakdowns)} teams")

    # Phase 6: Get LLM feedback survey metrics
    logger.info("Querying LLM feedback survey metrics")
    try:
        survey_metrics = get_llm_feedback_survey_metrics(period.start, period.end, team_ids)
    except Exception:
        logger.warning(
            "[AIO Usage Error] surveys query failed",
            phase="surveys",
            event_source="ai_observability_usage_report",
            exc_info=True,
        )
        # Re-raise so Celery's autoretry_for=(Exception,) kicks in. Do not swallow.
        raise
    logger.info(f"Retrieved survey metrics for {len(survey_metrics)} teams")

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
                "period_start": period.start.isoformat(),
                "period_end": period.end.isoformat(),
                "ai_generation_count": 0,
                "ai_embedding_count": 0,
                "ai_span_count": 0,
                "ai_trace_count": 0,
                "ai_trace_event_count": 0,
                "ai_metric_count": 0,
                "ai_feedback_count": 0,
                "ai_evaluation_count": 0,
                "ai_is_error_count": 0,
                "ai_llm_judge_evaluation_count": 0,
                "ai_hog_evaluation_count": 0,
                "ai_sentiment_evaluation_count": 0,
                "ai_trace_summary_count": 0,
                "ai_generation_summary_count": 0,
                "ai_trace_clusters_count": 0,
                "ai_generation_clusters_count": 0,
                "llm_prompt_fetched_count": 0,
                "active_llm_feedback_survey_count": 0,
                "llm_feedback_survey_response_count": 0,
                "total_ai_cost_usd": 0.0,
                "total_ai_cost_usd_count": 0,
                "total_ai_cost_usd_negative_count": 0,
                "total_ai_cost_usd_zero_count": 0,
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
            report["ai_trace_event_count"] += metrics.ai_trace_event_count
            report["ai_metric_count"] += metrics.ai_metric_count
            report["ai_feedback_count"] += metrics.ai_feedback_count
            report["ai_evaluation_count"] += metrics.ai_evaluation_count
            report["ai_is_error_count"] += metrics.ai_is_error_count
            report["ai_llm_judge_evaluation_count"] += metrics.ai_llm_judge_evaluation_count
            report["ai_hog_evaluation_count"] += metrics.ai_hog_evaluation_count
            report["ai_sentiment_evaluation_count"] += metrics.ai_sentiment_evaluation_count
            report["ai_trace_summary_count"] += metrics.ai_trace_summary_count
            report["ai_generation_summary_count"] += metrics.ai_generation_summary_count
            report["ai_trace_clusters_count"] += metrics.ai_trace_clusters_count
            report["ai_generation_clusters_count"] += metrics.ai_generation_clusters_count

            report["total_ai_cost_usd"] += metrics.total_cost
            report["total_ai_cost_usd_count"] += metrics.total_cost_count
            report["total_ai_cost_usd_negative_count"] += metrics.total_cost_negative_count
            report["total_ai_cost_usd_zero_count"] += metrics.total_cost_zero_count
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

        # Summing per-team distinct counts is exact at org level: a trace id belongs to one team.
        report["ai_trace_count"] += ai_trace_counts.get(team_id, 0)

        report["llm_prompt_fetched_count"] += llm_prompt_fetched_counts.get(team_id, 0)

        # Add LLM feedback survey metrics
        team_survey = survey_metrics.get(team_id)
        if team_survey:
            report["active_llm_feedback_survey_count"] += team_survey.active_survey_count
            report["llm_feedback_survey_response_count"] += team_survey.response_count

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

    logger.info(f"Generated AI observability reports for {len(org_reports)} organizations")
    return org_reports


@shared_task(
    name="posthog.tasks.llm_analytics_usage_report.capture_llm_analytics_report",
    max_retries=3,
    bind=True,
    **AI_OBSERVABILITY_USAGE_REPORT_TASK_KWARGS,
)
def capture_ai_observability_report(
    self: Task,
    *,
    organization_id: str | None = None,
    report_dict: dict[str, Any],
    at_date: str | None = None,
) -> None:
    """
    Capture AI observability usage report event for a specific organization.

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
            name=AI_OBSERVABILITY_USAGE_EVENT,
            organization_id=organization_id,
            properties=report_dict,
            timestamp=at_date,
        )
        logger.info(f"Captured AI observability usage report for organization {organization_id}")
    except Exception as err:
        log = logger.error if _is_final_attempt(self) else logger.warning
        log(
            "[AIO Usage Error] AI observability usage report sent to PostHog for organization failed",
            organization_id=organization_id,
            error=str(err),
            event_source="ai_observability_usage_report",
            exc_info=True,
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
            log(
                "[AIO Usage Error] Failed to capture error event",
                organization_id=organization_id,
                error=str(capture_err),
                event_source="ai_observability_usage_report",
                exc_info=True,
            )

        raise


@shared_task(
    name="posthog.tasks.llm_analytics_usage_report.send_llm_analytics_usage_reports",
    max_retries=3,
    bind=True,
    **AI_OBSERVABILITY_USAGE_REPORT_TASK_KWARGS,
)
def send_ai_observability_usage_reports(
    self: Task,
    dry_run: bool = False,
    at: str | None = None,
    organization_ids: list[str] | None = None,
) -> None:
    """
    Main task to send AI observability usage reports for all organizations.

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
        posthoganalytics.capture_exception(Exception(f"AI observability usage reports are disabled for {at}"))
        return

    at_date = parser.parse(at) if at else None
    period = get_previous_day(at=at_date)

    # An explicit date or org filter is what distinguishes an operator-triggered run from the daily
    # schedule.
    is_manual_run = bool(at or organization_ids)

    if organization_ids:
        logger.info(
            "Sending AI observability usage reports for specific organizations",
            org_count=len(organization_ids),
            organization_ids=organization_ids,
        )

    logger.info("Gathering AI observability usage data")
    query_time_start = datetime.now(UTC)

    try:
        # Every run consults this, not only operator-triggered ones. `acks_late` with
        # `reject_on_worker_lost` means a worker lost part way through the emission loop has its
        # message redelivered with the same arguments, and the scheduled run carries no date, so a
        # redelivered daily run would otherwise emit a second report for every organization it had
        # already dispatched. It runs before the gathering so that a lookup failure costs one query
        # rather than the whole five-query gather on each Celery retry, and inside this block so that
        # a permanent lookup failure still reaches the terminal log the alert alerts on.
        organizations_to_skip = _get_organizations_to_skip(period.start)
        org_reports = _get_all_ai_observability_reports(period=period)
    except Exception as err:
        # The log alert keys on error severity: retryable attempts stay warnings, only the
        # exhausted final attempt may page.
        if _is_final_attempt(self):
            logger.error(
                "[AIO Usage Error] usage report run failed permanently",
                error=str(err),
                period_start=period.start.isoformat(),
                period_end=period.end.isoformat(),
                retries=self.request.retries,
                event_source="ai_observability_usage_report",
                exc_info=True,
            )
        raise

    if organization_ids:
        original_count = len(org_reports)
        org_reports = {org_id: report for org_id, report in org_reports.items() if org_id in organization_ids}
        filtered_count = len(org_reports)
        missing_orgs = set(organization_ids) - set(org_reports.keys())

        logger.info(
            f"Filtered AI observability org reports from {original_count} to {filtered_count} organizations",
            requested_org_count=len(organization_ids),
            found_org_count=filtered_count,
            missing_orgs=missing_orgs or None,
        )

    # Applied before the dry-run return so that a dry run previews the organizations a real run would
    # report on, rather than the unfiltered set.
    if organizations_to_skip:
        before_count = len(org_reports)
        org_reports = {org_id: report for org_id, report in org_reports.items() if org_id not in organizations_to_skip}
        logger.info(
            "Skipped organizations that already have an AI observability report for this period",
            skipped_org_count=before_count - len(org_reports),
            remaining_org_count=len(org_reports),
            period_start=period.start.isoformat(),
        )

    query_time_duration = (datetime.now(UTC) - query_time_start).total_seconds()
    logger.info(f"Found {len(org_reports)} AI observability org reports. It took {query_time_duration} seconds.")

    if dry_run:
        logger.info("Dry run - not sending reports")
        return

    total_orgs = len(org_reports)
    total_orgs_sent = 0

    logger.info("Sending AI observability usage reports")

    # Deterministic nominal stamp (midnight after the covered day): keeps daily bucketing stable
    # in UTC and project timezones, and stops retry stragglers landing on the wrong chart day.
    # Actual arrival time remains queryable via events.created_at.
    report_timestamp = (period.start + REPORT_STAMP_OFFSET).isoformat()
    triggered_by = "manual" if is_manual_run else "scheduled"

    for org_id, report in org_reports.items():
        report["triggered_by"] = triggered_by
        try:
            capture_ai_observability_report.delay(
                organization_id=org_id,
                report_dict=report,
                at_date=report_timestamp,
            )
            total_orgs_sent += 1

        except Exception as err:
            logger.exception(
                "[AIO Usage Error] Failed to queue AI observability report for organization",
                organization_id=org_id,
                error=str(err),
                event_source="ai_observability_usage_report",
            )
            capture_exception(err)

    logger.info(
        f"Queued {total_orgs_sent}/{total_orgs} AI observability usage reports",
        total_orgs=total_orgs,
        total_orgs_sent=total_orgs_sent,
        region=get_instance_region(),
    )
