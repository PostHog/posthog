from datetime import timedelta

from ee.clickhouse.queries.clickhouse_session_recording import SessionRecording, query_sessions_in_range
from posthog.api.session_recording import SessionRecordingViewSet


class ClickhouseSessionRecordingViewSet(SessionRecordingViewSet):
    def get_session_recording_list(self, filter):
        return query_sessions_in_range(self.team, filter.date_from, filter.date_to + timedelta(days=1), filter)

    def get_session_recording(self, session_recording_id):
        return SessionRecording().run(team=self.team, session_recording_id=session_recording_id)
