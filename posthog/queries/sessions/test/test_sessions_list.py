from datetime import datetime

import pytz
from freezegun import freeze_time

from posthog.models import Action, ActionStep, Event, Organization, Person
from posthog.models.cohort import Cohort
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.sessions_list import SessionsList
from posthog.test.base import BaseTest


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def sessions_list_test_factory(sessions, event_factory):
    class TestSessionsList(BaseTest):
        def test_sessions_list(self):
            self.create_test_data()

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.run_query(SessionsFilter(data={"properties": []}))

                self.assertEqual(len(response), 2)
                self.assertEqual(response[0]["distinct_id"], "2")

                response = self.run_query(SessionsFilter(data={"properties": [{"key": "$os", "value": "Mac OS X"}]}))
                self.assertEqual(len(response), 1)

        def test_sessions_and_cohort(self):
            self.create_test_data()
            cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"email": "bla"}}])
            cohort.calculate_people()
            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.run_query(
                    SessionsFilter(data={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],})
                )
                self.assertEqual(len(response), 1)

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_filter_by_entity_event(self):
            self.create_test_data()

            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "event_type", "key": "id", "value": "custom-event"}]})
                ),
                2,
            )
            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "event_type", "key": "id", "value": "another-event"}]})
                ),
                1,
            )

            self.assertLength(
                self.run_query(
                    SessionsFilter(
                        data={
                            "filters": [
                                {"type": "event_type", "key": "id", "value": "custom-event"},
                                {"type": "event_type", "key": "id", "value": "another-event"},
                            ]
                        }
                    )
                ),
                1,
            )

            self.assertLength(
                self.run_query(
                    SessionsFilter(
                        data={
                            "filters": [
                                {
                                    "type": "event_type",
                                    "key": "id",
                                    "value": "custom-event",
                                    "properties": [{"key": "$os", "value": "Mac OS X"}],
                                }
                            ]
                        }
                    )
                ),
                1,
            )

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_filter_by_entity_action(self):
            action1 = _create_action(name="custom-event", team=self.team)
            action2 = _create_action(name="another-event", team=self.team)

            self.create_test_data()

            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "action_type", "key": "id", "value": action1.id}]})
                ),
                2,
            )
            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "action_type", "key": "id", "value": action2.id}]})
                ),
                1,
            )

            self.assertLength(
                self.run_query(
                    SessionsFilter(
                        data={
                            "filters": [
                                {
                                    "type": "action_type",
                                    "key": "id",
                                    "value": action1.id,
                                    "properties": [{"key": "$os", "value": "Mac OS X"}],
                                }
                            ]
                        }
                    )
                ),
                1,
            )

        @freeze_time("2012-01-15T04:15:00.000Z")
        def test_match_multiple_action_filters(self):
            self.create_test_data()

            sessions = self.run_query(
                SessionsFilter(
                    data={
                        "filters": [
                            {"type": "event_type", "key": "id", "value": "custom-event"},
                            {"type": "event_type", "key": "id", "value": "another-event"},
                        ]
                    }
                )
            )

            self.assertLength(sessions, 1)
            self.assertLength(sessions[0]["matching_events"], 3)

        def run_query(self, sessions_filter):
            return sessions().run(sessions_filter, self.team)[0]

        def assertLength(self, value, expected):
            self.assertEqual(len(value), expected)

        def create_test_data(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="$pageview", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="$pageview", distinct_id="2")
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="2")
                event_factory(team=self.team, event="custom-event", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="custom-event", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="custom-event", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="another-event", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T04:13:22.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="2")
            team_2 = Organization.objects.bootstrap(None)[2]
            Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            # Test team leakage
            Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})

    return TestSessionsList


class DjangoSessionsListTest(sessions_list_test_factory(SessionsList, Event.objects.create)):  # type: ignore
    pass
