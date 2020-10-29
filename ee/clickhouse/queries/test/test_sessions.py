from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.queries.test.test_sessions import sessions_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseSessions(ClickhouseTestMixin, sessions_test_factory(ClickhouseSessions, _create_event)):  # type: ignore
    def test_sessions_list_time_clamp(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="1st action", distinct_id="1")
            _create_event(team=self.team, event="1st action", distinct_id="2")
        with freeze_time("2012-01-14T03:25:34.000Z"):
            _create_event(team=self.team, event="2nd action", distinct_id="1")
            _create_event(team=self.team, event="2nd action", distinct_id="2")
        with freeze_time("2012-01-15T03:59:34.000Z"):
            _create_event(team=self.team, event="3rd action", distinct_id="2")
        with freeze_time("2012-01-15T03:59:35.000Z"):
            _create_event(team=self.team, event="3rd action", distinct_id="1")
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
            _create_event(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
            _create_event(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

        with freeze_time("2012-01-15T20:01:34.000Z"):
            for i in range(100, 201):
                _create_event(team=self.team, event="4th action", distinct_id=str(i), properties={"$os": "Mac OS X"})

        team_2 = Team.objects.create()
        Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
        # Test team leakage
        Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = ClickhouseSessions().run(Filter(data={"events": [], "session": None}), self.team)

        self.assertEqual(len(response), 50)
