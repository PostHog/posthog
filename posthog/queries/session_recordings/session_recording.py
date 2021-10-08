import datetime
from typing import Any, Dict, List, Optional, Tuple

from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import Person, SessionRecordingEvent, Team

DistinctId = str
Snapshots = List[Any]


class SessionRecording:
    _session_recording_id: str
    _team: Team

    def __init__(self, session_recording_id: str, team: Team) -> None:
        self._session_recording_id = session_recording_id
        self._team = team

    def query_recording_snapshots(self) -> Tuple[Optional[DistinctId], Optional[datetime.datetime], Snapshots]:
        events = SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )
        if len(events) == 0:
            return None, None, []
        return events[0].distinct_id, events[0].timestamp, [e.snapshot_data for e in events]

    def run(self) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, start_time, snapshots = self.query_recording_snapshots()
        snapshots = list(decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, snapshots))
        try:
            person = (
                PersonSerializer(Person.objects.get(team=self._team, persondistinctid__distinct_id=distinct_id)).data
                if distinct_id
                else None
            )
        except Person.DoesNotExist:
            person = None

        return {
            "snapshots": snapshots,
            "person": person,
            "start_time": start_time,
        }
