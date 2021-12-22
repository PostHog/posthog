from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

from django.utils.timezone import datetime, now
from freezegun import freeze_time

from posthog.models import Organization, SessionRecordingEvent, Team
from posthog.tasks.session_recording_retention import session_recording_retention
from posthog.test.base import BaseTest

threshold = now


class TestSessionRecording(BaseTest):
    def test_deletes_from_django(self) -> None:
        with freeze_time("2020-01-10"):
            self.create_snapshot("1", threshold() - timedelta(days=1, minutes=5))
            self.create_snapshot("1", threshold() - timedelta(days=1, minutes=10))
            self.create_snapshot("1", threshold() - timedelta(days=1, minutes=15))
            self.create_snapshot("2", threshold() - timedelta(days=2, minutes=20))
            event_after_threshold = self.create_snapshot("3", threshold() + timedelta(days=3))

            session_recording_retention(self.team.id, threshold().isoformat())

            self.assertEqual(SessionRecordingEvent.objects.count(), 1)
            self.assertEqual(SessionRecordingEvent.objects.last(), event_after_threshold)

    def create_snapshot(self, session_id: str, timestamp: datetime, window_id: str = "") -> SessionRecordingEvent:
        return SessionRecordingEvent.objects.create(
            team=self.team,
            distinct_id="distinct_id",
            timestamp=timestamp,
            snapshot_data={"timestamp": timestamp.timestamp()},
            session_id=session_id,
            window_id=window_id,
        )
