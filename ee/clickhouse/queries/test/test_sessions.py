from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from posthog.queries.test.test_sessions import sessions_test_factory


class TestClickhouseSessions(sessions_test_factory(ClickhouseSessions)):
    pass
