import dataclasses
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union, cast

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.request import Request

from posthog.helpers.session_recording import (
    DecompressedRecordingData,
    RecordingSegment,
    decompress_chunked_snapshot_data,
    generate_inactive_segments_for_range,
    get_active_segments_from_event_list,
)
from posthog.models import SessionRecordingEvent, Team


@dataclasses.dataclass
class RecordingMetadata:
    session_id: str
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Optional[Dict[str, Dict]]


class SessionRecording:
    _request: Request
    _session_recording_id: str
    _team: Team

    def __init__(self, request: Request, session_recording_id: str, team: Team) -> None:
        self._request = request
        self._session_recording_id = session_recording_id
        self._team = team

    def _query_recording_snapshots(self) -> Union[QuerySet, List[SessionRecordingEvent]]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    def get_snapshots(self, limit, offset) -> DecompressedRecordingData:
        all_recording_events = list(self._query_recording_snapshots())
        return decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_recording_events, limit, offset
        )

    def get_metadata(self) -> Optional[RecordingMetadata]:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return None

        segments, start_and_end_times_by_window_id = self._process_snapshots_for_metadata(all_snapshots)

        first_snapshot = all_snapshots[0]

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            session_id=first_snapshot.session_id,
            distinct_id=first_snapshot.distinct_id,
        )

    def _process_snapshots_for_metadata(self, all_snapshots) -> Tuple[List[RecordingSegment], Dict[str, Dict]]:
        decompressed_recording_data = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots, return_only_activity_data=True
        )

        start_and_end_times_by_window_id = {}

        # Get the active segments for each window_id
        all_active_segments: List[RecordingSegment] = []
        for window_id, event_list in decompressed_recording_data.snapshot_data_by_window_id.items():
            events_with_processed_timestamps = [
                {
                    "timestamp": datetime.fromtimestamp(event.get("timestamp", 0) / 1000, timezone.utc),
                    "is_active": event.get("is_active"),
                }
                for event in event_list
            ]
            # Not sure why, but events are sometimes slightly out of order
            events_with_processed_timestamps.sort(key=lambda x: cast(datetime, x["timestamp"]))

            active_segments_for_window_id = get_active_segments_from_event_list(
                events_with_processed_timestamps, window_id
            )

            all_active_segments.extend(active_segments_for_window_id)

            start_and_end_times_by_window_id[window_id] = {
                "start_time": events_with_processed_timestamps[0].get("timestamp"),
                "end_time": events_with_processed_timestamps[-1].get("timestamp"),
            }

        # Sort the active segments by start time. This will interleave active segments
        # from different windows
        all_active_segments.sort(key=lambda segment: segment.start_time)

        # These start and end times are used to make sure the segments span the entire recording
        first_start_time = min([cast(datetime, x["start_time"]) for x in start_and_end_times_by_window_id.values()])
        last_end_time = max([cast(datetime, x["end_time"]) for x in start_and_end_times_by_window_id.values()])

        # Now, we fill in the gaps between the active segments with inactive segments
        all_segments = []
        current_timestamp = first_start_time
        current_window_id = None
        for segment in all_active_segments:
            # It's possible that segments overlap and we don't need to fill a gap
            if segment.start_time > current_timestamp:
                all_segments.extend(
                    generate_inactive_segments_for_range(
                        current_timestamp, segment.start_time, current_window_id, start_and_end_times_by_window_id,
                    )
                )
            all_segments.append(segment)
            current_window_id = segment.window_id
            current_timestamp = max(segment.end_time, current_timestamp)

        if current_timestamp < last_end_time:
            all_segments.extend(
                generate_inactive_segments_for_range(
                    current_timestamp,
                    last_end_time,
                    current_window_id,
                    start_and_end_times_by_window_id,
                    is_last_segment=True,
                )
            )

        return all_segments, start_and_end_times_by_window_id
