from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.test.util import ClickhouseTestMixin
from posthog.queries.test.test_retention import retention_test_factory


class TestClickhouseRetention(ClickhouseTestMixin, retention_test_factory(ClickhouseRetention)):
    pass
