from freezegun import freeze_time

from posthog.models import Event, Person, Team
from posthog.models.cohort import Cohort
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions_list import SessionsList
from posthog.test.base import BaseTest


def sessions_list_test_factory(sessions, event_factory):
    class TestSessionsList(BaseTest):
        def test_sessions_list(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})
            team_2 = Team.objects.create()
            Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            # Test team leakage
            Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = sessions().run(SessionsFilter(data={"events": [], "session": None}), self.team)

            self.assertEqual(len(response), 2)
            self.assertEqual(response[0]["global_session_id"], 1)

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = sessions().run(
                    SessionsFilter(
                        data={"events": [], "properties": [{"key": "$os", "value": "Mac OS X"}], "session": None}
                    ),
                    self.team,
                )
            self.assertEqual(len(response), 1)

        def test_sessions_and_cohort(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})
            team_2 = Team.objects.create()
            Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            # Test team leakage
            Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"email": "bla"}}])
            cohort.calculate_people()
            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = sessions().run(
                    SessionsFilter(
                        data={
                            "events": [],
                            "session": None,
                            "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(len(response), 1)

    return TestSessionsList


class DjangoSessionsListTest(sessions_list_test_factory(SessionsList, Event.objects.create)):  # type: ignore
    pass
