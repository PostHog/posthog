from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Action, ActionStep, Cohort, Event, Organization, Person, SessionRecordingEvent
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.sessions_list import SessionsList
from posthog.tasks.calculate_action import calculate_action, calculate_actions_from_last_calculation
from posthog.test.base import BaseTest


def _create_action(team, name, properties=[]) -> Action:
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name, properties=properties)
    return action


def sessions_list_test_factory(sessions, event_factory, session_recording_event_factory):
    class TestSessionsList(BaseTest):
        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_sessions_list(self):
            self.create_test_data()

            response, _ = self.run_query(SessionsFilter(data={"properties": []}))

            self.assertEqual(len(response), 2)
            self.assertEqual(response[0]["distinct_id"], "2")

            response, _ = self.run_query(SessionsFilter(data={"properties": [{"key": "$os", "value": "Mac OS X"}]}))
            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["distinct_id"], "1")

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_sessions_list_keys(self):
            self.create_test_data()

            response, _ = self.run_query(SessionsFilter(data={"properties": []}))
            self.assertEqual(
                set(response[0].keys()) - {"email"},
                {
                    "distinct_id",
                    "global_session_id",
                    "length",
                    "start_time",
                    "end_time",
                    "start_url",
                    "end_url",
                    "matching_events",
                    "session_recordings",
                },
            )

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_start_end_url(self):
            self.create_test_data()

            response, _ = self.run_query(SessionsFilter(data={"properties": []}))
            self.assertDictContainsSubset(
                {"distinct_id": "2", "start_url": "aloha.com/2", "end_url": "aloha.com/lastpage"}, response[0]
            )
            self.assertDictContainsSubset({"distinct_id": "1", "start_url": None, "end_url": None}, response[1])

        def test_sessions_and_cohort(self):
            self.create_test_data()
            cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"email": "bla"}}])
            cohort.calculate_people()
            with freeze_time("2012-01-15T04:01:34.000Z"):
                response, _ = self.run_query(
                    SessionsFilter(data={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],})
                )
                self.assertEqual(len(response), 1)

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_sessions_by_distinct_id(self):
            self.create_large_testset()

            sessions, _ = self.run_query(SessionsFilter(data={"distinct_id": "88"}))
            self.assertLength(sessions, 1)
            self.assertEqual(sessions[0]["distinct_id"], "88")

            sessions, _ = self.run_query(SessionsFilter(data={"distinct_id": "foobar"}))
            self.assertLength(sessions, 0)

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_filter_by_entity_event(self):
            self.create_test_data()

            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "event_type", "key": "id", "value": "custom-event"}]})
                )[0],
                2,
            )
            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "event_type", "key": "id", "value": "another-event"}]})
                )[0],
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
                )[0],
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
                )[0],
                1,
            )

        @freeze_time("2012-01-15T04:01:34.000Z")
        def test_filter_by_entity_action(self):
            action1 = _create_action(
                name="custom-event", team=self.team, properties=[{"key": "$os", "value": "Windows 95"}]
            )
            action2 = _create_action(name="custom-event", team=self.team)
            action3 = _create_action(name="another-event", team=self.team)

            self.create_test_data()

            action1.calculate_events()
            action2.calculate_events()
            action3.calculate_events()

            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "action_type", "key": "id", "value": action1.id}]})
                )[0],
                1,
            )
            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "action_type", "key": "id", "value": action2.id}]})
                )[0],
                2,
            )
            self.assertLength(
                self.run_query(
                    SessionsFilter(data={"filters": [{"type": "action_type", "key": "id", "value": action3.id}]})
                )[0],
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
                                    "value": action2.id,
                                    "properties": [{"key": "$os", "value": "Mac OS X"}],
                                }
                            ]
                        }
                    )
                )[0],
                1,
            )

        @freeze_time("2012-01-15T04:15:00.000Z")
        def test_match_multiple_action_filters(self):
            self.create_test_data()

            sessions, _ = self.run_query(
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

        @freeze_time("2012-01-15T20:00:00.000Z")
        def test_filter_with_pagination(self):
            self.create_large_testset()

            sessions, pagination = self.run_query(
                SessionsFilter(data={"filters": [{"type": "person", "key": "email", "value": "person99@example.com"}]})
            )
            self.assertLength(sessions, 1)
            self.assertEqual(sessions[0]["distinct_id"], "99")
            self.assertIsNone(pagination)

            sessions, pagination = self.run_query(
                SessionsFilter(
                    data={
                        "filters": [
                            {
                                "type": "event_type",
                                "key": "id",
                                "value": "$pageview",
                                "properties": [{"key": "$some_property", "value": 88}],
                            }
                        ]
                    }
                )
            )
            self.assertLength(sessions, 1)
            self.assertEqual(sessions[0]["distinct_id"], "88")
            self.assertIsNone(pagination)

            sessions, pagination = self.run_query(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "gt", "value": 0}]}
                )
            )

            self.assertLength(sessions, 1)
            self.assertEqual(sessions[0]["distinct_id"], "77")
            self.assertIsNone(pagination)

            sessions, pagination = self.run_query(
                SessionsFilter(data={"filters": [{"type": "person", "key": "mod15", "value": 10}]})
            )
            self.assertEqual([session["distinct_id"] for session in sessions], ["10", "25", "40", "55", "70", "85"])
            self.assertIsNone(pagination)

            sessions, pagination = self.run_query(
                SessionsFilter(data={"filters": [{"type": "person", "key": "mod4", "value": 3}]})
            )
            self.assertEqual([session["distinct_id"] for session in sessions], list(map(str, range(3, 42, 4))))
            self.assertIsNotNone(pagination)

        def run_query(self, sessions_filter):
            return sessions.run(sessions_filter, self.team, limit=10)

        def assertLength(self, value, expected):
            self.assertEqual(len(value), expected)

        def create_test_data(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(
                    team=self.team, event="$pageview", distinct_id="2", properties={"$current_url": "aloha.com/1"}
                )
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="$pageview", distinct_id="2")
            with freeze_time("2012-01-15T03:58:34.000Z"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="2",
                    properties={"$os": "Windows 95", "$current_url": "aloha.com/2"},
                )
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="custom-event", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
                event_factory(team=self.team, event="custom-event", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="custom-event", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="another-event", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T04:13:22.000Z"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="2",
                    properties={"$current_url": "aloha.com/lastpage"},
                )
            team_2 = Organization.objects.bootstrap(None)[2]
            Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            # Test team leakage
            Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            calculate_actions_from_last_calculation()

        def create_large_testset(self):
            for i in range(100):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id=str(i),
                    timestamp=now() - relativedelta(minutes=i),
                    properties={"$some_property": i},
                )
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[str(i)],
                    properties={"email": f"person{i}@example.com", "mod15": i % 15, "mod4": i % 4},
                )

            session_recording_event_factory(
                team_id=self.team.pk,
                distinct_id="77",
                timestamp=now() - relativedelta(minutes=76),
                session_id="$ses_id",
                snapshot_data={"type": 2},
            )
            session_recording_event_factory(
                team_id=self.team.pk,
                distinct_id="77",
                timestamp=now() - relativedelta(minutes=78),
                session_id="$ses_id",
                snapshot_data={"type": 2},
            )

    return TestSessionsList


class DjangoSessionsListTest(sessions_list_test_factory(SessionsList, Event.objects.create, SessionRecordingEvent.objects.create)):  # type: ignore
    pass
