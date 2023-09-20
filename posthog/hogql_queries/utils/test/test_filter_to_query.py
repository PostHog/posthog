from posthog.hogql_queries.filter_to_query import filter_to_query
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.test.base import BaseTest
from posthog.models.filters.filter import Filter


class TestFilterToQuery(BaseTest):
    def test_base_trend(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "TrendsQuery")

    def test_base_funnel(self):
        filter = Filter(data={"insight": "FUNNELS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "FunnelsQuery")

    def test_base_retention_query(self):
        filter = Filter(data={"insight": "RETENTION"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "RetentionQuery")

    def test_base_retention_query_from_retention_filter(self):
        filter = RetentionFilter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "RetentionQuery")

    def test_base_paths_query(self):
        filter = Filter(data={"insight": "PATHS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "PathsQuery")

    def test_base_path_query_from_path_filter(self):
        filter = PathFilter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "PathsQuery")

    def test_base_lifecycle_query(self):
        filter = Filter(data={"insight": "LIFECYCLE"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "LifecycleQuery")

    def test_base_stickiness_query(self):
        filter = Filter(data={"insight": "STICKINESS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "StickinessQuery")

    def test_base_stickiness_query_from_stickiness_filter(self):
        filter = StickinessFilter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "StickinessQuery")

    def test_date_range_default(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.dateRange.date_from, "-7d")
        self.assertEqual(query.dateRange.date_to, None)

    def test_date_range_custom(self):
        filter = Filter(data={"date_from": "-14d", "date_to": "-7d"})

        query = filter_to_query(filter)

        self.assertEqual(query.dateRange.date_from, "-14d")
        self.assertEqual(query.dateRange.date_to, "-7d")

    def test_interval_default(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.interval, "day")

    def test_interval_custom(self):
        filter = Filter(data={"interval": "hour"})

        query = filter_to_query(filter)

        self.assertEqual(query.interval, "hour")
