from uuid import uuid4

from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.queries.sessions.list import ClickhouseSessionsList
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models import GroupTypeMapping, Person
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.test.test_sessions import sessions_test_factory
from posthog.queries.sessions.test.test_sessions_list import sessions_list_test_factory


def _create_event(**kwargs):
    create_event(event_uuid=uuid4(), **kwargs)


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessions(ClickhouseTestMixin, sessions_test_factory(ClickhouseSessions, _create_event, Person.objects.create)):  # type: ignore
    @snapshot_clickhouse_queries
    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_group_filter(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        # Only checks whether the query crashes or not
        ClickhouseSessions().run(
            SessionsFilter(
                data={
                    "interval": "day",
                    "session": "avg",
                    "events": [{"id": "1st action"},],
                    "properties": [{"key": "property", "value": 5, "type": "group", "group_type_index": 0}],
                },
                team=self.team,
            ),
            self.team,
        )


class TestClickhouseSessionsList(ClickhouseTestMixin, sessions_list_test_factory(ClickhouseSessionsList, _create_event, _create_session_recording_event)):  # type: ignore
    pass
