from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from posthog.queries.test.test_trends import TestTrends


class TestClickhouseTrends(TestTrends):
    def _initialize(self):
        self._trends = ClickhouseTrends
