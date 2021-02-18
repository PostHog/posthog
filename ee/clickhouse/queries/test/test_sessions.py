from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.queries.sessions.list import ClickhouseSessionsList
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.sessions.test.test_sessions import sessions_test_factory
from posthog.queries.sessions.test.test_sessions_list import sessions_list_test_factory


def _create_event(**kwargs):
    create_event(event_uuid=uuid4(), **kwargs)


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessions(ClickhouseTestMixin, sessions_test_factory(ClickhouseSessions, _create_event)):  # type: ignore
    pass


class TestClickhouseSessionsList(ClickhouseTestMixin, sessions_list_test_factory(ClickhouseSessionsList, _create_event, _create_session_recording_event)):  # type: ignore
    pass
