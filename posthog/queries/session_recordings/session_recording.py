from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models import QuerySet
from rest_framework.request import Request

from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import Person, SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.sessions.session_recording import RECORDINGS_NUM_SNAPSHOTS_LIMIT
from posthog.queries.sessions.utils import cached_recording
from posthog.utils import format_query_params_absolute_url, get_milliseconds_between_dates

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

    def query_recording_snapshots(self) -> Union[QuerySet, List[SessionRecordingEvent]]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    # @cached_recording TODO: uncomment once it's determined safe to cache session recordings
    def get_snapshot_data(self) -> Tuple[Optional[DistinctId], Optional[datetime], Snapshots]:
        events = self.query_recording_snapshots()
        if len(events) == 0:
            return None, None, []
        return (
            events[0].distinct_id,
            events[0].timestamp,
            list(
                decompress_chunked_snapshot_data(
                    self._team.pk, self._session_recording_id, [e.snapshot_data for e in events]
                )
            ),
        )

    def run(self) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, start_time, snapshots = self.get_snapshot_data()

        # Apply limit and offset after decompressing to account for non-fully formed chunks.
        snapshots_subset = snapshots[self._offset : (self._offset + self._limit)]
        duration = 0
        if len(snapshots) > 1:
            duration = get_milliseconds_between_dates(
                datetime.fromtimestamp(snapshots[-1].get("timestamp", 0) / 1000.0),
                datetime.fromtimestamp(snapshots[0].get("timestamp", 0) / 1000.0),
            )
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
