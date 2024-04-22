from posthog.caching.fetch_from_cache import InsightResult
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
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
    return filter_to_query(filter.to_dict())


def _cached_response_to_insight_result(response: CachedQueryResponse) -> InsightResult:
    response_dict = response.model_dump()
    result_keys = InsightResult.__annotations__.keys()

    # replace 'result' with 'results' for schema compatibility
    response_keys = ["results" if key == "result" else key for key in result_keys]

    # use only the keys of the response that are also present in the result
    result = InsightResult(
        **{result_key: response_dict[response_key] for result_key, response_key in zip(result_keys, response_keys)}
    )
    return result


def process_insight(insight: Insight, team: Team) -> InsightResult:
    query = _insight_to_query(insight, team)
    response = LifecycleQueryRunner(query=query, team=team).run(refresh_requested=False)
    return _cached_response_to_insight_result(response)
