from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from requests import Request

from posthog.decorators import cached_recording
from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import Person, SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.sessions.session_recording import RECORDINGS_NUM_SNAPSHOTS_LIMIT
from posthog.utils import format_query_params_absolute_url, get_seconds_between_dates

DistinctId = str
Snapshots = List[Any]
Events = Tuple[str, str, Snapshots]


class SessionRecording:
    _request: Request
    _filter: SessionRecordingsFilter
    _session_recording_id: str
    _team: Team
    _limit: int
    _offset: int

    def __init__(
        self, request: Request, filter: SessionRecordingsFilter, session_recording_id: str, team: Team
    ) -> None:
        self._request = request
        self._filter = filter
        self._session_recording_id = session_recording_id
        self._team = team
        self._limit = self._filter.limit if self._filter.limit else RECORDINGS_NUM_SNAPSHOTS_LIMIT
        self._offset = self._filter.offset if self._filter.offset else 0

    @cached_recording
    def query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    def get_snapshot_data(self) -> Tuple[Optional[DistinctId], Optional[datetime], Optional[int], Snapshots]:
        events = self.query_recording_snapshots()

        if len(events) == 0:
            return None, None, None, []

        return (
            events.first().distinct_id,
            events.first().timestamp,
            get_seconds_between_dates(events.last().timestamp, events.first().timestamp),
            [e.snapshot_data for e in events],
        )

    def run(self) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, start_time, duration, snapshots = self.query_recording_snapshots()
        # Apply limit and offset after decompressing to account for non-fully formed chunks.
        snapshots = list(decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, snapshots))
        snapshots_subset = snapshots[self._offset : (self._offset + self._limit)]
        has_next = len(snapshots) > (self._offset + self._limit + 1)

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if has_next
            else None
        )

        try:
            person = (
                PersonSerializer(Person.objects.get(team=self._team, persondistinctid__distinct_id=distinct_id)).data
                if distinct_id
                else None
            )
        except Person.DoesNotExist:
            person = None

        return {
            "snapshots": snapshots_subset,
            "person": person,
            "start_time": start_time,
            "next": next_url,
            "duration": duration,
        }
