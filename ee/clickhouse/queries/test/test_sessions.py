from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_sessions import sessions_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseSessions(ClickhouseTestMixin, sessions_test_factory(ClickhouseSessions, _create_event)):  # type: ignore
    pass
