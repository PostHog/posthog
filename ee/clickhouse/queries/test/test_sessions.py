from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from posthog.queries.test.test_sessions import sessions_test_factory


class TestClickhouseSessions(sessions_test_factory(ClickhouseSessions, create_event)):
    pass
