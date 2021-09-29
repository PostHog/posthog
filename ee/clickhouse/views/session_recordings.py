from ee.clickhouse.queries.session_recordings.session_recording import ClickhouseSessionRecording
from ee.clickhouse.queries.session_recordings.session_recording_list import ClickhouseSessionRecordingList
from posthog.api.session_recording import SessionRecordingViewSet


class ClickhouseSessionRecordingViewSet(SessionRecordingViewSet):
    def _get_session_recording_list(self, filter):
        return ClickhouseSessionRecordingList(filter=filter, team=self.team).run()

    def _get_session_recording(self, session_recording_id):
        return ClickhouseSessionRecording(team=self.team, session_recording_id=session_recording_id).run()
