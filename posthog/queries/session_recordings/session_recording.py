import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, cast

from rest_framework.request import Request
from statshog.defaults.django import statsd

from posthog.client import sync_execute
from posthog.helpers.session_recording import (
    DecompressedRecordingData,
    RecordingMetadata,
    RecordingSegment,
    SessionRecordingEvent,
    SessionRecordingEventSummary,
    SnapshotDataTaggedWithWindowId,
    WindowId,
    decompress_chunked_snapshot_data,
    generate_inactive_segments_for_range,
    get_active_segments_from_event_list,
    parse_snapshot_timestamp,
)
from posthog.models import Team


class SessionRecording:
    _request: Request
    _session_recording_id: str
    _recording_start_time: Optional[datetime]
    _team: Team

    def __init__(
        self, request: Request, session_recording_id: str, team: Team, recording_start_time: Optional[datetime] = None
    ) -> None:
        self._request = request
        self._session_recording_id = session_recording_id
        self._team = team
        self._recording_start_time = recording_start_time

    _recording_snapshot_query = """
        SELECT {fields}
        FROM session_recording_events
        PREWHERE
            team_id = %(team_id)s
            AND session_id = %(session_id)s
            {date_clause}
        ORDER BY timestamp
        {limit_param}
    """

    def get_recording_snapshot_date_clause(self) -> Tuple[str, Dict]:
        if self._recording_start_time:
            # If we can, we want to limit the time range being queried.
            # Theoretically, we shouldn't have to look before the recording start time,
            # but until we straighten out the recording start time logic, we should have a buffer
            return (
                """
                    AND toTimeZone(toDateTime(timestamp, 'UTC'), %(timezone)s) >= toDateTime(%(start_time)s, %(timezone)s) - INTERVAL 1 DAY
                    AND toTimeZone(toDateTime(timestamp, 'UTC'), %(timezone)s) <= toDateTime(%(start_time)s, %(timezone)s) + INTERVAL 2 DAY
            """,
                {"start_time": self._recording_start_time, "timezone": self._team.timezone},
            )
        return ("", {})

    def _query_recording_snapshots(self, include_snapshots=False) -> List[SessionRecordingEvent]:
        fields = ["session_id", "window_id", "distinct_id", "timestamp", "events_summary"]
        if include_snapshots:
            fields.append("snapshot_data")

        date_clause, date_clause_params = self.get_recording_snapshot_date_clause()
        query = self._recording_snapshot_query.format(date_clause=date_clause, fields=", ".join(fields), limit_param="")

        response = sync_execute(
            query, {"team_id": self._team.id, "session_id": self._session_recording_id, **date_clause_params}
        )

        return [
            SessionRecordingEvent(
                session_id=columns[0],
                window_id=columns[1],
                distinct_id=columns[2],
                timestamp=columns[3],
                events_summary=[json.loads(x) for x in columns[4]] if columns[4] else [],
                snapshot_data=json.loads(columns[5]) if len(columns) > 5 else None,
            )
            for columns in response
        ]

    # Fast constant time query that checks if session exists.
    def query_session_exists(self) -> bool:
        date_clause, date_clause_params = self.get_recording_snapshot_date_clause()
        query = self._recording_snapshot_query.format(
            date_clause=date_clause, fields="session_id", limit_param="LIMIT 1"
        )
        response = sync_execute(
            query, {"team_id": self._team.id, "session_id": self._session_recording_id, **date_clause_params}
        )
        return bool(response)

    def get_snapshots(self, limit, offset) -> DecompressedRecordingData:
        all_snapshots = [
            SnapshotDataTaggedWithWindowId(
                window_id=recording_snapshot["window_id"], snapshot_data=recording_snapshot["snapshot_data"]
            )
            for recording_snapshot in self._query_recording_snapshots(include_snapshots=True)
        ]
        return decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, all_snapshots, limit, offset)

    def get_metadata(self) -> Optional[RecordingMetadata]:
        snapshots = self._query_recording_snapshots(include_snapshots=False)

        if len(snapshots) == 0:
            return None

        distinct_id = snapshots[0]["distinct_id"]

        events_summary_by_window_id = self._get_events_summary_by_window_id(snapshots)

        if events_summary_by_window_id:
            # If all snapshots contain the new events_summary field...
            statsd.incr("session_recordings.metadata_parsed_from_events_summary")
            segments, start_and_end_times_by_window_id = self._get_recording_segments_from_events_summary(
                events_summary_by_window_id
            )
        else:
            # ... otherwise use the legacy method
            snapshots = self._query_recording_snapshots(include_snapshots=True)
            statsd.incr("session_recordings.metadata_parsed_from_snapshot_data")
            segments, start_and_end_times_by_window_id = self._get_recording_segments_from_snapshot(snapshots)

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            distinct_id=cast(str, distinct_id),
        )

    def _get_events_summary_by_window_id(
        self, snapshots: List[SessionRecordingEvent]
    ) -> Optional[Dict[WindowId, List[SessionRecordingEventSummary]]]:
        """
        For a list of snapshots, group all the events_summary by window_id.
        If any of them are missing this field, we return empty to fallback to old parsing method
        """
        events_summary_by_window_id: Dict[WindowId, List[SessionRecordingEventSummary]] = {}

        for snapshot in snapshots:
            if snapshot["window_id"] not in events_summary_by_window_id:
                events_summary_by_window_id[snapshot["window_id"]] = []

            events_summary_by_window_id[snapshot["window_id"]].extend(
                [cast(SessionRecordingEventSummary, x) for x in snapshot["events_summary"]]
            )
            events_summary_by_window_id[snapshot["window_id"]].sort(key=lambda x: x["timestamp"])

        # If any of the snapshots are missing the events_summary field, we fallback to the old parsing method
        if any(len(x) == 0 for x in events_summary_by_window_id.values()):
            return None

        return events_summary_by_window_id

    def _get_recording_segments_from_snapshot(
        self, snapshots: List[SessionRecordingEvent]
    ) -> Tuple[List[RecordingSegment], Dict[WindowId, RecordingSegment]]:
        """
        !Deprecated!
        This method supports parsing of events_summary info for entries that were created before this field was added

        """
        all_snapshots: List[SnapshotDataTaggedWithWindowId] = [
            SnapshotDataTaggedWithWindowId(window_id=snapshot["window_id"], snapshot_data=snapshot["snapshot_data"])
            for snapshot in snapshots
        ]

        decompressed_recording_data = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots, return_only_activity_data=True
        )

        events_summary_by_window_id = {
            window_id: cast(List[SessionRecordingEventSummary], event_list)
            for window_id, event_list in decompressed_recording_data["snapshot_data_by_window_id"].items()
        }

        return self._get_recording_segments_from_events_summary(events_summary_by_window_id)

    def _get_recording_segments_from_events_summary(
        self, events_summary_by_window_id: Dict[WindowId, List[SessionRecordingEventSummary]]
    ) -> Tuple[List[RecordingSegment], Dict[WindowId, RecordingSegment]]:
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

        start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment] = {}

        # Get the active segments for each window_id
        all_active_segments: List[RecordingSegment] = []

        for window_id, events_summary in events_summary_by_window_id.items():
            active_segments_for_window_id = get_active_segments_from_event_list(events_summary, window_id)

            all_active_segments.extend(active_segments_for_window_id)

            start_and_end_times_by_window_id[window_id] = RecordingSegment(
                window_id=window_id,
                start_time=parse_snapshot_timestamp(events_summary[0]["timestamp"]),
                end_time=parse_snapshot_timestamp(events_summary[-1]["timestamp"]),
                is_active=False,  # We don't know yet
            )

        # Sort the active segments by start time. This will interleave active segments
        # from different windows
        all_active_segments.sort(key=lambda segment: segment["start_time"])

        # These start and end times are used to make sure the segments span the entire recording
        first_start_time = min([cast(datetime, x["start_time"]) for x in start_and_end_times_by_window_id.values()])
        last_end_time = max([cast(datetime, x["end_time"]) for x in start_and_end_times_by_window_id.values()])

        # Now, we fill in the gaps between the active segments with inactive segments
        all_segments: List[RecordingSegment] = []
        current_timestamp = first_start_time
        current_window_id: WindowId = sorted(
            start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
        )[0]

        for index, segment in enumerate(all_active_segments):
            # It's possible that segments overlap and we don't need to fill a gap
            if segment["start_time"] > current_timestamp:
                all_segments.extend(
                    generate_inactive_segments_for_range(
                        current_timestamp,
                        segment["start_time"],
                        current_window_id,
                        start_and_end_times_by_window_id,
                        is_first_segment=index == 0,
                    )
                )
            all_segments.append(segment)
            current_window_id = segment["window_id"]
            current_timestamp = max(segment["end_time"], current_timestamp)

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
