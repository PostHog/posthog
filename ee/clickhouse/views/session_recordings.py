from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import (
    ClickhouseSessionRecordingMetaData,
    ClickhouseSessionRecordingSnapshots,
)
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from posthog.api.session_recording import SessionRecordingViewSet


class ClickhouseSessionRecordingViewSet(SessionRecordingViewSet):
    def _get_session_recording_list(self, filter):
        return ClickhouseSessionRecordingList(filter=filter, team=self.team).run()

    def _get_session_recording_snapshots(self, request, filter, session_recording_id):
        return ClickhouseSessionRecordingSnapshots(
            request=request, filter=filter, team=self.team, session_recording_id=session_recording_id
        ).run()

    def _get_session_recording_meta_data(self, request, session_recording_id):
        return ClickhouseSessionRecordingMetaData(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).run()
