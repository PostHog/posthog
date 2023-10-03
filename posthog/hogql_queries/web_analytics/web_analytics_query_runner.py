from abc import ABC

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql_queries.query_runner import QueryRunner


class WebAnalyticsQueryRunner(QueryRunner, ABC):
    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
