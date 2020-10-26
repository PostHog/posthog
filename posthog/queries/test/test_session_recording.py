import datetime

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Event
from posthog.queries.session_recording import SessionRecording, add_session_recording_ids


def session_recording_test_factory(session_recording, event_factory):
    class TestSessionRecording(BaseTest):
        def test_query_run(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                snapshots = session_recording().run(team=self.team, filter=None, session_recording_id="1")
                self.assertEqual(
                    snapshots,
                    [{"timestamp": 1_600_000_000}, {"timestamp": 1_600_000_010}, {"timestamp": 1_600_000_030},],
                )

        def test_query_run_with_no_such_session(self):
            snapshots = session_recording().run(team=self.team, filter=None, session_recording_id="xxx")
            self.assertEqual(snapshots, [])

        def test_add_session_recording_ids(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now() + relativedelta(seconds=5))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=33))
                # :TRICKY: same user, different session at the same time
                self.create_snapshot("user", "3", now() + relativedelta(seconds=15))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=40))
                self.create_snapshot("user", "4", now() + relativedelta(seconds=999))
                self.create_snapshot("user", "4", now() + relativedelta(seconds=1020))

                sessions = [
                    {"distinct_id": "user", "start_time": now(), "end_time": now() + relativedelta(seconds=100)},
                    {
                        "distinct_id": "user",
                        "start_time": now() + relativedelta(hours=99),
                        "end_time": now() + relativedelta(hours=100),
                    },
                    {"distinct_id": "user2", "start_time": now(), "end_time": now() + relativedelta(seconds=30)},
                ]
                results = add_session_recording_ids(self.team, sessions)
                self.assertEqual([r["session_recording_ids"] for r in results], [["1", "3"], [], ["2"]])

        def test_query_run_with_no_sessions(self):
            self.assertEqual(add_session_recording_ids(self.team, []), [])

        def create_snapshot(self, distinct_id, session_id, timestamp):
            event_factory(
                team=self.team,
                distinct_id=distinct_id,
                timestamp=timestamp,
                event="$snapshot",
                properties={"$snapshot_data": {"timestamp": timestamp.timestamp()}, "$session_id": session_id,},
            )

    return TestSessionRecording


class DjangoSessionRecordingTest(session_recording_test_factory(SessionRecording, Event.objects.create)):  # type: ignore
    pass
