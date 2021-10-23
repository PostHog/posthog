from datetime import datetime, timedelta
from typing import List, Optional, TypedDict, Union

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.request import Request

from posthog.helpers.session_recording import SnapshotData, paginate_chunk_decompression
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.utils import format_query_params_absolute_url


class RecordingMetadata(TypedDict):
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration: Optional[timedelta]
    session_id: Optional[str]
    distinct_id: Optional[str]


class RecordingSnapshots(TypedDict):
    next: Optional[str]
    snapshots: List[SnapshotData]


DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value


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
        self._limit = self._filter.limit if self._filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        self._offset = self._filter.offset if self._filter.offset else 0

    def _query_recording_snapshots(self) -> Union[QuerySet, List[SessionRecordingEvent]]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    def get_snapshots(self) -> RecordingSnapshots:
        all_recording_snapshots = [event.snapshot_data for event in list(self._query_recording_snapshots())]
        paginated_chunks = paginate_chunk_decompression(
            self._team.pk, self._session_recording_id, all_recording_snapshots, self._limit, self._offset
        )

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if paginated_chunks.has_next
            else None
        )

        return RecordingSnapshots(next=next_url, snapshots=paginated_chunks.paginated_list)

    def _get_first_and_last_chunk(self, all_recording_snapshots: List[SnapshotData]):
        paginated_list_with_first_chunk = paginate_chunk_decompression(
            self._team.pk, self._session_recording_id, all_recording_snapshots, 1, 0
        )

        paginated_list_with_last_chunk = paginate_chunk_decompression(
            self._team.pk, self._session_recording_id, list(reversed(all_recording_snapshots)), 1, 0
        )

        return (
            paginated_list_with_first_chunk.paginated_list,
            paginated_list_with_last_chunk.paginated_list,
        )

    def get_metadata(self) -> RecordingMetadata:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return RecordingMetadata(start_time=None, end_time=None, duration=None, session_id=None, distinct_id=None,)

        snapshot_data_list = [event.snapshot_data for event in list(self._query_recording_snapshots())]
        first_chunk, last_chunk = self._get_first_and_last_chunk(snapshot_data_list)

        first_event = first_chunk[0]
        first_event_timestamp = datetime.fromtimestamp(first_event.get("timestamp") / 1000, timezone.utc)

        last_event = last_chunk[-1]
        last_event_timestamp = datetime.fromtimestamp(last_event.get("timestamp") / 1000, timezone.utc)

        first_snapshot = all_snapshots[0]

        return RecordingMetadata(
            start_time=first_event_timestamp,
            end_time=last_event_timestamp,
            duration=last_event_timestamp - first_event_timestamp,
            session_id=first_snapshot.session_id,
            distinct_id=first_snapshot.distinct_id,
        )
