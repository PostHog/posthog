from posthog.caching.fetch_from_cache import InsightResult
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.query_runner import CachedQueryResponse
from posthog.models.filters.filter import Filter as LegacyFilter
from posthog.models.filters.path_filter import PathFilter as LegacyPathFilter
from posthog.models.filters.retention_filter import RetentionFilter as LegacyRetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter as LegacyStickinessFilter
from posthog.models.insight import Insight
from posthog.models.team.team import Team
from posthog.types import InsightQueryNode


# sync with frontend/src/queries/utils.ts
def is_insight_with_hogql_support(insight: Insight):
    if insight.filters.get("insight") == "LIFECYCLE":
        return True
    else:
        return False


def _insight_to_query(insight: Insight, team: Team) -> InsightQueryNode:
    if insight.filters.get("insight") == "RETENTION":
        filter = LegacyRetentionFilter(data=insight.filters, team=team)
    elif insight.filters.get("insight") == "PATHS":
        filter = LegacyPathFilter(data=insight.filters, team=team)
    elif insight.filters.get("insight") == "STICKINESS":
        filter = LegacyStickinessFilter(data=insight.filters, team=team)
    else:
        filter = LegacyFilter(data=insight.filters, team=team)
    return filter_to_query(filter)


def _cached_response_to_insight_result(response: CachedQueryResponse) -> InsightResult:
    result = InsightResult(**response, cache_key="todo", timezone="UTC")  # TODO cache_key, timezone
    return result


def process_insight(insight: Insight, team: Team) -> InsightResult:
    query = _insight_to_query(insight, team)
    # response = process_query(team, query_json=query)
    # refresh_requested = refresh_requested_by_client(request) if request else False
    lifecycle_query_runner = LifecycleQueryRunner(query=query, team=team)
    # return _unwrap_pydantic_dict(lifecycle_query_runner.run(refresh_requested=refresh_requested))
    response = lifecycle_query_runner.run(refresh_requested=False)

    result = _cached_response_to_insight_result(response)
    return result
