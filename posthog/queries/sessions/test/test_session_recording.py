from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Person, SessionRecordingEvent
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.session_recording import SessionRecording, filter_sessions_by_recordings
from posthog.test.base import BaseTest


def session_recording_test_factory(session_recording, filter_sessions, event_factory):
    class TestSessionRecording(BaseTest):
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
                self.create_snapshot("user", "4", now() + relativedelta(seconds=999))
                self.create_snapshot("user", "4", now() + relativedelta(seconds=1020))

                self.create_snapshot("broken-user", "5", now() + relativedelta(seconds=10), type=3)
                self.create_snapshot("broken-user", "5", now() + relativedelta(seconds=20), type=3)

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

                self.assertEqual([r["session_recording_ids"] for r in results], expected)

        def test_filter_sessions_by_recordings(self):
            self._test_filter_sessions(SessionsFilter(data={"offset": 0}), [["1", "3"], [], ["2"], []])

        def test_filter_sessions_by_recording_duration_gt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "gt", "value": 15}]}
                ),
                [["1", "3"]],
            )

        def test_filter_sessions_by_recording_duration_lt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "lt", "value": 30}]}
                ),
                [["1"], ["2"]],
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

    return TestSessionRecording


class DjangoSessionRecordingTest(
    session_recording_test_factory(SessionRecording, filter_sessions_by_recordings, SessionRecordingEvent.objects.create)  # type: ignore
):
    pass
