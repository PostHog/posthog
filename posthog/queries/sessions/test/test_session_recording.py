from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Person, User
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.session_recording_event import SessionRecordingEvent, SessionRecordingViewed
from posthog.queries.sessions.session_recording import SessionRecording, join_with_session_recordings
from posthog.test.base import BaseTest


def session_recording_test_factory(session_recording, filter_sessions, event_factory):
    class TestSessionRecording(BaseTest):
        maxDiff = None

        def test_query_run(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})

                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                session = session_recording().run(team=self.team, session_recording_id="1")
                self.assertEqual(
                    session["snapshots"],
                    [
                        {"timestamp": 1_600_000_000, "type": 2},
                        {"timestamp": 1_600_000_010, "type": 2},
                        {"timestamp": 1_600_000_030, "type": 2},
                    ],
                )
                self.assertEqual(session["person"]["properties"], {"$some_prop": "something"})
                self.assertEqual(session["start_time"], now())

        def test_query_run_with_no_such_session(self):
            session = session_recording().run(team=self.team, session_recording_id="xxx")
            self.assertEqual(session, {"snapshots": [], "person": None, "start_time": None})

        def _test_filter_sessions(self, filter, expected):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now() + relativedelta(seconds=5))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=33))
                # :TRICKY: same user, different session at the same time
                self.create_snapshot("user", "3", now() + relativedelta(seconds=15))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=60))
                self.create_chunked_snapshot(
                    "user", "4", now() + relativedelta(seconds=999), {"chunk_id": "afb", "has_full_snapshot": True}
                )
                self.create_snapshot("user", "4", now() + relativedelta(seconds=1020), type=1)

                self.create_snapshot("broken-user", "5", now() + relativedelta(seconds=10), type=3)
                self.create_chunked_snapshot(
                    "broken-user",
                    "5",
                    now() + relativedelta(seconds=20),
                    {"chunk_id": "afb", "has_full_snapshot": False},
                )

                sessions = [
                    {"distinct_id": "user", "start_time": now(), "end_time": now() + relativedelta(seconds=100)},
                    {
                        "distinct_id": "user",
                        "start_time": now() + relativedelta(hours=99),
                        "end_time": now() + relativedelta(hours=100),
                    },
                    {"distinct_id": "user2", "start_time": now(), "end_time": now() + relativedelta(seconds=30)},
                    {"distinct_id": "broken-user", "start_time": now(), "end_time": now() + relativedelta(seconds=100)},
                ]

                results = filter_sessions(self.team, sessions, filter)
                session_recording_results = [r["session_recordings"] for r in results]
                for session_recording_package in session_recording_results:
                    for session_recording in session_recording_package:
                        # TODO: Include start_time and end_time in asserts
                        del session_recording["start_time"]
                        del session_recording["end_time"]
                self.assertEqual([r["session_recordings"] for r in results], expected)

        def test_join_with_session_recordings(self):
            _, team2, user2 = User.objects.bootstrap("Test2", "sessions@posthog.com", None)

            SessionRecordingViewed.objects.create(team=self.team, user_id=self.user.pk, session_id="1")
            SessionRecordingViewed.objects.create(team=team2, user_id=user2.pk, session_id="2")

            self._test_filter_sessions(
                SessionsFilter(data={"user_id": self.user.pk}),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": True},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ],
                    [],
                    [{"id": "2", "recording_duration": 13, "viewed": False}],
                    [],
                ],
            )

        def test_filter_sessions_by_recording_duration_gt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "gt", "value": 15}]}
                ),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": False},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ]
                ],
            )

        def test_filter_sessions_by_unseen_recording(self):
            SessionRecordingViewed.objects.create(team=self.team, user_id=self.user.pk, session_id="2")
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "unseen", "value": 1}], "user_id": self.user.pk}
                ),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": False},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ]
                ],
            )

        def test_filter_sessions_by_recording_duration_lt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "lt", "value": 30}]}
                ),
                [
                    [{"id": "1", "recording_duration": 25, "viewed": False}],
                    [{"id": "2", "recording_duration": 13, "viewed": False}],
                ],
            )

        def test_query_run_with_no_sessions(self):
            self.assertEqual(filter_sessions(self.team, [], SessionsFilter(data={"offset": 0})), [])

        def create_snapshot(self, distinct_id, session_id, timestamp, type=2):
            event_factory(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                snapshot_data={"timestamp": timestamp.timestamp(), "type": type},
            )

        def create_chunked_snapshot(self, distinct_id, session_id, timestamp, snapshot_data):
            event_factory(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                snapshot_data=snapshot_data,
            )

    return TestSessionRecording


class DjangoSessionRecordingTest(
    session_recording_test_factory(SessionRecording, join_with_session_recordings, SessionRecordingEvent.objects.create)  # type: ignore
):
    pass
