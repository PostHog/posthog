from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, TypedDict, Union

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.request import Request

from posthog.helpers.session_recording import (
    SnapshotData,
    decompress_chunked_snapshot_data,
    is_active_event,
    paginate_chunk_decompression,
)
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.utils import format_query_params_absolute_url


class RecordingMetadata(TypedDict, total=False):
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration: Optional[timedelta]
    session_id: Optional[str]
    distinct_id: Optional[str]
    active_segments_by_window_id: Optional[Dict[str, List]]


class RecordingSnapshots(TypedDict):
    next: Optional[str]
    snapshots: List[SnapshotData]


DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value

ACTIVITY_THRESHOLD_SECONDS = (
    60  # Minimum time between two active events for a active recording segment to be continued vs split
)


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

    def get_metadata(self, include_active_segments=False) -> RecordingMetadata:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return RecordingMetadata(start_time=None, end_time=None, duration=None, session_id=None, distinct_id=None,)

        snapshot_data_list = [event.snapshot_data for event in list(all_snapshots)]
        first_chunk, last_chunk = self._get_first_and_last_chunk(snapshot_data_list)

        first_event = first_chunk[0]
        first_event_timestamp = datetime.fromtimestamp(first_event.get("timestamp") / 1000, timezone.utc)

        last_event = last_chunk[-1]
        last_event_timestamp = datetime.fromtimestamp(last_event.get("timestamp") / 1000, timezone.utc)

        first_snapshot = all_snapshots[0]

        recording_metadata = RecordingMetadata(
            start_time=first_event_timestamp,
            end_time=last_event_timestamp,
            duration=last_event_timestamp - first_event_timestamp,
            session_id=first_snapshot.session_id,
            distinct_id=first_snapshot.distinct_id,
        )
        if include_active_segments:
            recording_metadata["active_segments_by_window_id"] = self._get_active_segments_by_window_id(all_snapshots)

        return recording_metadata

    def _get_active_segments(self, snapshots):
        # Takes a list of snapshots and returns a list of active segments with start and end times
        snapshot_data_list = [event.snapshot_data for event in list(snapshots)]

        active_event_timestamps = []
        for data in decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, snapshot_data_list):
            if is_active_event(data):
                active_event_timestamps.append(datetime.fromtimestamp(data.get("timestamp", 0) / 1000, timezone.utc))

        active_recording_segments: List[Dict[str, datetime]] = []

        current_active_segment: Optional[Dict[str, datetime]] = None

        for current_timestamp in active_event_timestamps:
            # If the time since the last active event is less than the threshold, continue the existing segment
            if current_active_segment and (current_timestamp - current_active_segment["end_time"]) <= timedelta(
                seconds=ACTIVITY_THRESHOLD_SECONDS
            ):
                current_active_segment["end_time"] = current_timestamp

            # Otherwise, start a new segment
            else:
                if current_active_segment:
                    active_recording_segments.append(current_active_segment)
                current_active_segment = {
                    "start_time": current_timestamp,
                    "end_time": current_timestamp,
                }

        # Add the last segment if it hasn't already been added
        if current_active_segment and (
            len(active_recording_segments) == 0 or active_recording_segments[-1] != current_active_segment
        ):
            active_recording_segments.append(current_active_segment)

        return active_recording_segments

    def _get_active_segments_by_window_id(self, all_snapshots):
        snapshots_by_window_id = defaultdict(list)
        for event in all_snapshots:
            snapshots_by_window_id[event.window_id].append(event)

        active_segments_by_window_id = {}

        for window_id, snapshots in snapshots_by_window_id.items():
            active_segments_by_window_id[window_id] = self._get_active_segments(snapshots)

        return active_segments_by_window_id
