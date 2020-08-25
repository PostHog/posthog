from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from posthog.queries.test.test_trends import trend_test_factory


class TestClickhouseTrends(trend_test_factory(ClickhouseTrends)):
    pass
