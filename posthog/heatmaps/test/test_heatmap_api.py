from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    @snapshot_clickhouse_queries
    def test_wat(self) -> None:
        pass
