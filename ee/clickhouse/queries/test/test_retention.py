from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from posthog.queries.test.test_retention import retention_test_factory


class TestClickhouseRetention(retention_test_factory(ClickhouseRetention)):
    pass
