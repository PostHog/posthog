from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_trends import trend_test_factory


class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends)):
    pass
