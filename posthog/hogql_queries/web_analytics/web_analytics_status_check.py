from typing import Type

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import WebAnalyticsStatusCheckResponse, WebAnalyticsStatusCheckQuery


class WebAnalyticsStatusCheckQueryRunner(QueryRunner):
    query: WebAnalyticsStatusCheckQuery
    query_type = WebAnalyticsStatusCheckQuery

    def to_query(self):
        return None

    def calculate(self):
        return WebAnalyticsStatusCheckResponse(
            results={"isSendingPageViewEvents": True, "isSendingPageLeaveEvents": True}
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
