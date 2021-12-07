import dataclasses
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.request import Request

from posthog.helpers.session_recording import SnapshotData, decompress_chunked_snapshot_data
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.utils import format_query_params_absolute_url


@dataclasses.dataclass
class RecordingSegment:
    start_time: datetime
    end_time: datetime
    window_id: str
    is_active: bool


@dataclasses.dataclass
class RecordingMetadata:
    session_id: str
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Optional[Dict[str, Dict]]


@dataclasses.dataclass
class DecompressedRecordingSnapshots:
    snapshot_data_by_window_id: Dict[str, List[SnapshotData]]
    next_url: str


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

    def get_snapshots(self) -> DecompressedRecordingSnapshots:
        all_recording_events = list(self._query_recording_snapshots())
        decompressed_recording_data = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_recording_events, self._limit, self._offset
        )

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if decompressed_recording_data.has_next
            else None
        )

        return DecompressedRecordingSnapshots(
            snapshot_data_by_window_id=decompressed_recording_data.snapshot_data_by_window_id, next_url=next_url
        )

    def get_metadata(self) -> RecordingMetadata:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return RecordingMetadata(start_time=None, end_time=None, duration=None, session_id=None, distinct_id=None,)

        segments, start_and_end_times_by_window_id = self._process_snapshots_for_metadata(all_snapshots)

        first_snapshot = all_snapshots[0]

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            session_id=first_snapshot.session_id,
            distinct_id=first_snapshot.distinct_id,
        )

    @staticmethod
    def _get_active_segments_for_window_id(event_list, window_id) -> List[RecordingSegment]:
        """
        Processes a list of events for a specific window_id to determine
        the segments of the recording where the user is "active". Active end 
        when there isn't another active event for ACTIVITY_THRESHOLD_SECONDS seconds
        """
        active_event_timestamps = [event.get("timestamp") for event in event_list if event.get("is_active")]

        active_recording_segments: List[RecordingSegment] = []
        current_active_segment: Optional[RecordingSegment] = None
        for current_timestamp in active_event_timestamps:
            # If the time since the last active event is less than the threshold, continue the existing segment
            if current_active_segment and (current_timestamp - current_active_segment.end_time) <= timedelta(
                seconds=ACTIVITY_THRESHOLD_SECONDS
            ):
                current_active_segment.end_time = current_timestamp

            # Otherwise, start a new segment
            else:
                if current_active_segment:
                    active_recording_segments.append(current_active_segment)
                current_active_segment = RecordingSegment(
                    start_time=current_timestamp, end_time=current_timestamp, window_id=window_id, is_active=True,
                )

        # Add the active last segment if it hasn't already been added
        if current_active_segment and (
            len(active_recording_segments) == 0 or active_recording_segments[-1] != current_active_segment
        ):
            active_recording_segments.append(current_active_segment)

        return active_recording_segments

    @staticmethod
    def _generate_inactive_segments_for_range(
        segment_start_time: datetime,
        segment_end_time: datetime,
        start_window_id: Optional[str],
        start_and_end_times_by_window_id: Dict[str, Dict],
        is_last_segment: bool = False,
    ) -> List[RecordingSegment]:
        window_ids_by_start_time = sorted(
            start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
        )

        # Order of window_ids to use for generating inactive segments. Start with the window_id of the
        # last active segment, then try the other window_ids in order of start_time
        window_id_priority_list = (
            [start_window_id] + window_ids_by_start_time if start_window_id else window_ids_by_start_time
        )

        inactive_segments = []
        current_time = segment_start_time

        for window_id in window_id_priority_list:
            window_start_time = start_and_end_times_by_window_id[window_id]["start_time"]
            window_end_time = start_and_end_times_by_window_id[window_id]["end_time"]
            if window_end_time > current_time and current_time < segment_end_time:
                # Add/subtract a millisecond to make sure the segments don't exactly overlap
                segment_start_time = max(window_start_time, current_time) + timedelta(milliseconds=1)
                segment_end_time = min(segment_end_time, window_end_time) - timedelta(
                    milliseconds=0 if is_last_segment else 1
                )
                inactive_segments.append(
                    RecordingSegment(
                        start_time=segment_start_time, end_time=segment_end_time, window_id=window_id, is_active=False,
                    )
                )
                current_time = min(segment_end_time, window_end_time)
        return inactive_segments

    def _process_snapshots_for_metadata(self, all_snapshots) -> Tuple[List[RecordingSegment], Dict[str, Dict]]:
        decompressed_recording_data = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots, return_only_activity_data=True
        )

        # Start and end times are used to make sure the segments span the entire recording
        first_start_time: Optional[datetime] = None
        last_end_time: Optional[datetime] = None

        all_active_segments: List[RecordingSegment] = []
        start_and_end_times_by_window_id = {}

        for window_id, event_list in decompressed_recording_data.snapshot_data_by_window_id.items():
            events_with_processed_timestamps = [
                {
                    "timestamp": datetime.fromtimestamp(event.get("timestamp", 0) / 1000, timezone.utc),
                    "is_active": event.get("is_active"),
                }
                for event in event_list
            ]
            # Not sure why, but events are sometimes slightly out of order
            events_with_processed_timestamps.sort(key=lambda x: x.get("timestamp"))

            active_segments_for_window_id = self._get_active_segments_for_window_id(
                events_with_processed_timestamps, window_id
            )

            all_active_segments.extend(active_segments_for_window_id)
            window_id_start_time = events_with_processed_timestamps[0].get("timestamp")
            window_id_end_time = events_with_processed_timestamps[-1].get("timestamp")

            start_and_end_times_by_window_id[window_id] = {
                "start_time": window_id_start_time,
                "end_time": window_id_end_time,
            }

            if not first_start_time or window_id_start_time < first_start_time:
                first_start_time = window_id_start_time
            if not last_end_time or window_id_end_time > last_end_time:
                last_end_time = window_id_end_time

        # Sort the active segments by start time. This will interleave active segments
        # from different windows
        all_active_segments.sort(key=lambda segment: segment.start_time)

        # Now, we fill in the gaps between the active segments with inactive segments
        all_segments = []
        current_timestamp = first_start_time
        current_window_id = None
        for segment in all_active_segments:
            # It's possible that segments overlap and we don't need to fill a gap
            if segment.start_time > current_timestamp:
                all_segments.extend(
                    self._generate_inactive_segments_for_range(
                        current_timestamp, segment.start_time, current_window_id, start_and_end_times_by_window_id,
                    )
                )
            all_segments.append(segment)
            current_window_id = segment.window_id
            current_timestamp = max(segment.end_time, current_timestamp)

        if current_timestamp < last_end_time:
            all_segments.extend(
                self._generate_inactive_segments_for_range(
                    current_timestamp,
                    last_end_time,
                    current_window_id,
                    start_and_end_times_by_window_id,
                    is_last_segment=True,
                )
            )

        return all_segments, start_and_end_times_by_window_id
