import dataclasses
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, cast

from rest_framework.request import Request

from posthog.helpers.session_recording import (
    DecompressedRecordingData,
    EventActivityData,
    RecordingSegment,
    SnapshotDataTaggedWithWindowId,
    WindowId,
    decompress_chunked_snapshot_data,
    generate_inactive_segments_for_range,
    get_active_segments_from_event_list,
)
from posthog.models import SessionRecordingEvent, Team


@dataclasses.dataclass
class RecordingMetadata:
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Dict[WindowId, Dict]


class SessionRecording:
    _request: Request
    _session_recording_id: str
    _team: Team

    def __init__(self, request: Request, session_recording_id: str, team: Team) -> None:
        self._request = request
        self._session_recording_id = session_recording_id
        self._team = team

    def _query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        raise NotImplementedError()

    def get_snapshots(self, limit, offset) -> DecompressedRecordingData:
        all_snapshots = [
            SnapshotDataTaggedWithWindowId(
                window_id=recording_snapshot.window_id, snapshot_data=recording_snapshot.snapshot_data
            )
            for recording_snapshot in self._query_recording_snapshots()
        ]
        return decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, all_snapshots, limit, offset)

    def get_metadata(self) -> Optional[RecordingMetadata]:
        all_snapshots: List[SnapshotDataTaggedWithWindowId] = []

        distinct_id = None
        for index, session_recording_event in enumerate(self._query_recording_snapshots()):
            if index == 0:
                distinct_id = session_recording_event.distinct_id
            all_snapshots.append(
                SnapshotDataTaggedWithWindowId(
                    window_id=session_recording_event.window_id, snapshot_data=session_recording_event.snapshot_data
                )
            )

        if len(all_snapshots) == 0:
            return None

        segments, start_and_end_times_by_window_id = self._process_snapshots_for_metadata(all_snapshots)

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            distinct_id=cast(str, distinct_id),
        )

    def _process_snapshots_for_metadata(self, all_snapshots) -> Tuple[List[RecordingSegment], Dict[WindowId, Dict]]:
        """
        This function processes the recording events into metadata.

        A recording can be composed of events from multiple windows/tabs. Recording events are seperated by
        `window_id`, so the playback experience is consistent (changes in one tab don't impact the recording
        of a different tab). However, we still want to playback the recording to the end user as the user interacted
        with their product.

        This function creates a "playlist" of recording segments that designates the order in which the front end
        should flip between players of different windows/tabs. To create this playlist, this function does the following:

        (1) For each recording event, we determine if it is "active" or not. An active event designates user
        activity (e.g. mouse movement).

        (2) We then generate "active segments" based on these lists of events. Active segments are segments
        of recordings where the maximum time between events determined to be active is less than a threshold (set to 60 seconds).

        (3) Next, we merge the active segments from all of the window_ids + sort them by start time. We now have the
        list of active segments. (note, it's very possible that active segments overlap if a user is flipping back
        and forth between tabs)

        (4) To complete the recording, we fill in the gaps between active segments with "inactive segments". In
        determining which window should be used for the inactive segment, we try to minimize the switching of windows.
        """

        decompressed_recording_data = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots, return_only_activity_data=True
        )

        start_and_end_times_by_window_id = {}

        # Get the active segments for each window_id
        all_active_segments: List[RecordingSegment] = []
        for window_id, event_list in decompressed_recording_data.snapshot_data_by_window_id.items():
            events_with_processed_timestamps = [
                EventActivityData(
                    timestamp=datetime.fromtimestamp(event.get("timestamp", 0) / 1000, timezone.utc),
                    is_active=event.get("is_active", False),
                )
                for event in event_list
            ]
            # Not sure why, but events are sometimes slightly out of order
            events_with_processed_timestamps.sort(key=lambda x: cast(datetime, x.timestamp))

            active_segments_for_window_id = get_active_segments_from_event_list(
                events_with_processed_timestamps, window_id
            )

            all_active_segments.extend(active_segments_for_window_id)

            start_and_end_times_by_window_id[window_id] = {
                "start_time": events_with_processed_timestamps[0].timestamp,
                "end_time": events_with_processed_timestamps[-1].timestamp,
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
        current_window_id: WindowId = sorted(
            start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
        )[0]

        for index, segment in enumerate(all_active_segments):
            # It's possible that segments overlap and we don't need to fill a gap
            if segment.start_time > current_timestamp:
                all_segments.extend(
                    generate_inactive_segments_for_range(
                        current_timestamp,
                        segment.start_time,
                        current_window_id,
                        start_and_end_times_by_window_id,
                        is_first_segment=index == 0,
                    )
                )
            all_segments.append(segment)
            current_window_id = segment.window_id
            current_timestamp = max(segment.end_time, current_timestamp)

        # If the last segment ends before the recording ends, we need to fill in the gap
        if current_timestamp < last_end_time:
            all_segments.extend(
                generate_inactive_segments_for_range(
                    current_timestamp,
                    last_end_time,
                    current_window_id,
                    start_and_end_times_by_window_id,
                    is_last_segment=True,
                    is_first_segment=current_timestamp == first_start_time,
                )
            )

        return all_segments, start_and_end_times_by_window_id
