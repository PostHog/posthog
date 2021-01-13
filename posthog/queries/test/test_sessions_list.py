from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Action, ActionStep, Event, Organization, Person
from posthog.models.cohort import Cohort
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions_list import SessionListBuilder, SessionsList
from posthog.test.base import BaseTest


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def sessions_list_test_factory(sessions, event_factory, action_filter_enabled):
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

        if action_filter_enabled:

            def test_filter_by_entity_event(self):
                self.create_test_data()

                with freeze_time("2012-01-15T04:01:34.000Z"):
                    self.assertLength(
                        self.run_query(
                            SessionsFilter(
                                data={"filters": [{"type": "event_type", "key": "id", "value": "custom-event"}]}
                            )
                        ),
                        2,
                    )
                    self.assertLength(
                        self.run_query(
                            SessionsFilter(
                                data={"filters": [{"type": "event_type", "key": "id", "value": "another-event"}]}
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

            def test_filter_by_entity_action(self):
                action1 = _create_action(name="custom-event", team=self.team)
                action2 = _create_action(name="another-event", team=self.team)

                self.create_test_data()

                with freeze_time("2012-01-15T04:01:34.000Z"):
                    self.assertLength(
                        self.run_query(
                            SessionsFilter(
                                data={"filters": [{"type": "action_type", "key": "id", "value": action1.id}]}
                            )
                        ),
                        2,
                    )
                    self.assertLength(
                        self.run_query(
                            SessionsFilter(
                                data={"filters": [{"type": "action_type", "key": "id", "value": action2.id}]}
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
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="$pageview", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="custom-event", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="custom-event", distinct_id="2", properties={"$os": "Windows 95"})
                event_factory(team=self.team, event="another-event", distinct_id="2", properties={"$os": "Windows 95"})
            team_2 = Organization.objects.bootstrap(None)[2]
            Person.objects.create(team=self.team, distinct_ids=["1", "3", "4"], properties={"email": "bla"})
            # Test team leakage
            Person.objects.create(team=team_2, distinct_ids=["1", "3", "4"], properties={"email": "bla"})

    return TestSessionsList


class DjangoSessionsListTest(sessions_list_test_factory(SessionsList, Event.objects.create, action_filter_enabled=False)):  # type: ignore
    pass


class MockEvent:
    def __init__(self, distinct_id, timestamp, current_url=None):
        self.distinct_id = distinct_id
        self.timestamp = timestamp
        self.current_url = current_url


@freeze_time("2021-01-13")
class TestSessionListBuilder(BaseTest):
    def build(self, events, **kwargs):
        self.builder = SessionListBuilder(iter(events), limit=2, **kwargs)
        self.builder.build()
        return self.builder.sessions

    def test_returns_sessions_for_single_user(self):
        sessions = self.build(
            [
                MockEvent("1", now()),
                MockEvent("1", now() - relativedelta(minutes=3)),
                MockEvent("1", now() - relativedelta(minutes=7)),
                MockEvent("1", now() - relativedelta(minutes=35)),
                MockEvent("1", now() - relativedelta(minutes=99)),
                MockEvent("1", now() - relativedelta(minutes=102)),
            ]
        )

        self.assertEqual(len(sessions), 2)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "end_time": now(),
                "start_time": now() - relativedelta(minutes=35),
                "event_count": 4,
                "length": 35 * 60,
                "end_url": None,
                "start_url": None,
            },
            sessions[0],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "end_time": now() - relativedelta(minutes=99),
                "start_time": now() - relativedelta(minutes=102),
                "event_count": 2,
                "length": 3 * 60,
                "end_url": None,
                "start_url": None,
            },
            sessions[1],
        )

        self.assertEqual(self.builder.pagination, None)

    def test_returns_parallel_sessions_with_pagination(self):
        events = [
            MockEvent("1", now()),
            MockEvent("2", now() - relativedelta(minutes=3)),
            MockEvent("3", now() - relativedelta(minutes=7)),
            MockEvent("2", now() - relativedelta(minutes=25)),
            MockEvent("1", now() - relativedelta(minutes=27)),
            MockEvent("1", now() - relativedelta(minutes=35)),
            MockEvent("2", now() - relativedelta(minutes=45)),
            MockEvent("1", now() - relativedelta(minutes=85)),
            MockEvent("1", now() - relativedelta(minutes=88)),
        ]

        page1 = self.build(events)

        self.assertEqual(len(page1), 2)
        self.assertDictContainsSubset(
            {"distinct_id": "1", "end_time": now(), "start_time": now() - relativedelta(minutes=35), "event_count": 3},
            page1[0],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "end_time": now() - relativedelta(minutes=3),
                "start_time": now() - relativedelta(minutes=45),
                "event_count": 3,
            },
            page1[1],
        )

        self.assertEqual(
            self.builder.pagination,
            {
                "offset": 2,
                "last_seen": {
                    "1": (now() - relativedelta(minutes=35)).timestamp(),
                    "2": (now() - relativedelta(minutes=45)).timestamp(),
                },
                "start_timestamp": (now() - relativedelta(minutes=3)).timestamp(),
            },
        )

        page2 = self.build(events[2:], last_page_last_seen=self.builder.pagination["last_seen"])
        self.assertEqual(len(page2), 2)
        self.assertDictContainsSubset(
            {
                "distinct_id": "3",
                "end_time": now() - relativedelta(minutes=7),
                "start_time": now() - relativedelta(minutes=7),
                "event_count": 1,
            },
            page2[0],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "end_time": now() - relativedelta(minutes=85),
                "start_time": now() - relativedelta(minutes=88),
                "event_count": 2,
            },
            page2[1],
        )

        self.assertEqual(self.builder.pagination, None)

    def test_current_url_set(self):
        sessions = self.build(
            [
                MockEvent("1", now()),
                MockEvent("2", now() - relativedelta(minutes=3), "http://foo.bar/landing"),
                MockEvent("2", now() - relativedelta(minutes=25)),
                MockEvent("1", now() - relativedelta(minutes=27)),
                MockEvent("1", now() - relativedelta(minutes=35)),
                MockEvent("2", now() - relativedelta(minutes=45), "http://foo.bar/subpage"),
            ]
        )

        self.assertEqual(len(sessions), 2)
        self.assertDictContainsSubset({"distinct_id": "1", "start_url": None, "end_url": None}, sessions[0])
        self.assertDictContainsSubset(
            {"distinct_id": "2", "start_url": "http://foo.bar/landing", "end_url": "http://foo.bar/subpage"},
            sessions[1],
        )
