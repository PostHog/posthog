from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import ClickhouseSessionRecording
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from posthog.api.session_recording import SessionRecordingViewSet


class ClickhouseSessionRecordingViewSet(SessionRecordingViewSet):
    def _get_session_recording_list(self, filter):
        return ClickhouseSessionRecordingList(filter=filter, team_id=self.team.pk).run()

    def _get_session_recording_snapshots(self, request, session_recording_id, limit, offset):
        return ClickhouseSessionRecording(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).get_snapshots(limit, offset)

    def _get_session_recording_meta_data(self, request, session_recording_id):
        return ClickhouseSessionRecording(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).get_metadata()
