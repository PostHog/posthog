from ee.clickhouse.client import ch_client
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_sessions import sessions_test_factory


# class TestClickhouseSessions(ClickhouseTestMixin, sessions_test_factory(ClickhouseSessions, create_event)):
class TestClickhouseSession:
    pass
