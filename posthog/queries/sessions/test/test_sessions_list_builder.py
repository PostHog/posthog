from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.queries.sessions.sessions_list_builder import SessionListBuilder
from posthog.test.base import BaseTest


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

    def test_email_current_url_set(self):
        sessions = self.build(
            [
                MockEvent("1", now()),
                MockEvent("2", now() - relativedelta(minutes=3), "http://foo.bar/landing"),
                MockEvent("2", now() - relativedelta(minutes=25)),
                MockEvent("1", now() - relativedelta(minutes=27)),
                MockEvent("1", now() - relativedelta(minutes=35)),
                MockEvent("2", now() - relativedelta(minutes=45), "http://foo.bar/subpage"),
            ],
            emails={"2": "foo@bar.com"},
        )

        self.assertEqual(len(sessions), 2)
        self.assertDictContainsSubset(
            {"distinct_id": "1", "start_url": None, "end_url": None, "email": None}, sessions[0]
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "start_url": "http://foo.bar/landing",
                "end_url": "http://foo.bar/subpage",
                "email": "foo@bar.com",
            },
            sessions[1],
        )

    def test_handles_session_ordering(self):
        sessions = self.build(
            [
                MockEvent("1", now()),
                MockEvent("2", now() - relativedelta(minutes=3)),
                MockEvent("2", now() - relativedelta(minutes=7)),
                MockEvent("1", now() - relativedelta(minutes=25)),
                MockEvent("2", now() - relativedelta(minutes=999)),
            ]
        )

        self.assertEqual([session["distinct_id"] for session in sessions], ["1", "2"])
