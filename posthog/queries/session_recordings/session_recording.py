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
    paginate_chunk_decompression_by_window_id,
)
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.utils import format_query_params_absolute_url


class RecordingMetadata(TypedDict, total=False):
    session_id: Optional[str]
    distinct_id: Optional[str]
    active_segments_by_window_id: Optional[Dict[str, List]]
    start_and_end_times_by_window_id: Optional[Dict[str, Dict]]


class RecordingSnapshots(TypedDict):
    next: Optional[str]
    snapshots: Dict[str, List[SnapshotData]]


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
        all_recording_events = list(self._query_recording_snapshots())
        paginated_chunks = paginate_chunk_decompression_by_window_id(
            self._team.pk, self._session_recording_id, all_recording_events, self._limit, self._offset
        )

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if paginated_chunks["has_next"]
            else None
        )

        return {
            "snapshot_data_by_window_id": paginated_chunks["snapshot_data_by_window_id"],
            "next": next_url,
        }

    def get_metadata(self, include_active_segments=False) -> RecordingMetadata:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return RecordingMetadata(start_time=None, end_time=None, duration=None, session_id=None, distinct_id=None,)

        segments, start_and_end_times_by_window_id = self._get_segment_playlist(all_snapshots)

        first_snapshot = all_snapshots[0]

        return RecordingMetadata(
            segment_playlist=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            session_id=first_snapshot.session_id,
            distinct_id=first_snapshot.distinct_id,
        )

    def _get_metadata_for_window_id(self, snapshots, window_id):
        # Takes a list of snapshots for a specific window_id and returns a list of segments active and inactive segments
        snapshot_data_list = [event.snapshot_data for event in list(snapshots)]

        active_event_timestamps = []
        start_time = None
        end_time = None
        for data in decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, snapshot_data_list):
            timestamp = datetime.fromtimestamp(data.get("timestamp", 0) / 1000, timezone.utc)
            if is_active_event(data):
                active_event_timestamps.append(timestamp)
            start_time = min(timestamp, start_time) if start_time else timestamp
            end_time = max(timestamp, end_time) if end_time else timestamp

        # Not sure why, but events are sometimes slightly out of order
        # active_event_timestamps.sort()

        # Create list of active segments
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
                    "window_id": window_id,
                    "is_active": True,
                }

        # Add the active last segment if it hasn't already been added
        if current_active_segment and (
            len(active_recording_segments) == 0 or active_recording_segments[-1] != current_active_segment
        ):
            active_recording_segments.append(current_active_segment)

        return {
            "active_segments": active_recording_segments,
            "start_time": start_time,
            "end_time": end_time,
        }

    def _generate_inactive_segments_for_range(
        self,
        segment_start_time,
        segment_end_time,
        start_window_id,
        start_and_end_times_by_window_id,
        is_last_segment=False,
    ):
        window_ids_by_start_time = sorted(
            start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
        )
        # Order of window_ids to use for generating inactive segments
        window_id_priority_list = [start_window_id] + window_ids_by_start_time

        inactive_segments = []
        current_time = segment_start_time
        for window_id in window_id_priority_list:
            window_start_time = start_and_end_times_by_window_id[window_id]["start_time"]
            window_end_time = start_and_end_times_by_window_id[window_id]["end_time"]
            if window_end_time > current_time and current_time < segment_end_time:
                inactive_segments.append(
                    {
                        # Add/subtract a millisecond to make sure the segments don't exactly overlap
                        "start_time": max(window_start_time, current_time) + timedelta(milliseconds=1),
                        "end_time": min(segment_end_time, window_end_time)
                        - timedelta(milliseconds=0 if is_last_segment else 1),
                        "window_id": window_id,
                        "is_active": False,
                    }
                )
                current_time = min(segment_end_time, window_end_time)
        return inactive_segments

    def _get_segment_playlist(self, all_snapshots):
        snapshots_by_window_id = defaultdict(list)
        for event in all_snapshots:
            snapshots_by_window_id[event.window_id].append(event)

        all_active_segments = []
        start_and_end_times_by_window_id = {}

        first_start_time = None
        first_window_id = None
        last_end_time = None

        for window_id, snapshots in snapshots_by_window_id.items():
            window_id_metadata = self._get_metadata_for_window_id(snapshots, window_id)
            all_active_segments.extend(window_id_metadata["active_segments"])
            start_and_end_times_by_window_id[window_id] = {
                "start_time": window_id_metadata["start_time"],
                "end_time": window_id_metadata["end_time"],
            }
            if not first_start_time or window_id_metadata["start_time"] < first_start_time:
                first_start_time = window_id_metadata["start_time"]
                first_window_id = window_id
            if not last_end_time or window_id_metadata["end_time"] > last_end_time:
                last_end_time = window_id_metadata["end_time"]

        all_active_segments.sort(key=lambda segment: segment["start_time"])

        current_timestamp = first_start_time
        current_window_id = first_window_id

        segment_playlist = []

        for segment in all_active_segments:
            if segment["start_time"] > current_timestamp:
                segment_playlist.extend(
                    self._generate_inactive_segments_for_range(
                        current_timestamp, segment["start_time"], current_window_id, start_and_end_times_by_window_id,
                    )
                )

            segment_playlist.append(segment)
            current_window_id = segment["window_id"]
            current_timestamp = max(segment["end_time"], current_timestamp)

        if current_timestamp < last_end_time:
            segment_playlist.extend(
                self._generate_inactive_segments_for_range(
                    current_timestamp,
                    last_end_time,
                    current_window_id,
                    start_and_end_times_by_window_id,
                    is_last_segment=True,
                )
            )

        return segment_playlist, start_and_end_times_by_window_id
