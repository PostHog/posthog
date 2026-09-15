from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags, tag_queries
from posthog.hogql_queries.utils.caller_context import map_in_caller_context


class TestMapInCallerContext(SimpleTestCase):
    def tearDown(self):
        reset_query_tags()
        super().tearDown()

    @patch("posthog.hogql_queries.utils.caller_context.TEST", False)
    def test_query_tags_survive_into_the_worker_threads(self):
        tag_queries(feature=Feature.CACHE_WARMUP, trigger="staleRevalidation")
        seen: dict[int, tuple] = {}

        def build(item: int) -> int:
            seen[item] = (get_query_tag_value("feature"), get_query_tag_value("trigger"))
            return item * 10

        result = map_in_caller_context(build, [1, 2, 3])

        assert result == [10, 20, 30]
        assert all(tags == (Feature.CACHE_WARMUP, "staleRevalidation") for tags in seen.values()), seen
