import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, cast

from statshog.defaults.django import statsd

from posthog.client import sync_execute
from posthog.models import Team
from posthog.models.session_recording.metadata import (
    DecompressedRecordingData,
    RecordingMetadata,
    SessionRecordingEvent,
    SessionRecordingEventSummary,
    SnapshotDataTaggedWithWindowId,
    WindowId,
)
from posthog.session_recordings.session_recording_helpers import (
    decompress_chunked_snapshot_data,
    get_metadata_from_events_summary,
)


class SessionRecordingEvents:
    _session_recording_id: str
    _recording_start_time: Optional[datetime]
    _team: Team

    def __init__(self, session_recording_id: str, team: Team, recording_start_time: Optional[datetime] = None) -> None:
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

    def get_snapshots(self, limit, offset) -> Optional[DecompressedRecordingData]:
        all_snapshots = [
            SnapshotDataTaggedWithWindowId(
                window_id=recording_snapshot["window_id"], snapshot_data=recording_snapshot["snapshot_data"]
            )
            for recording_snapshot in self._query_recording_snapshots(include_snapshots=True)
        ]
        decompressed = decompress_chunked_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots, limit, offset
        )

        if decompressed["snapshot_data_by_window_id"] == {}:
            return None
        return decompressed

    def get_metadata(self) -> Optional[RecordingMetadata]:
        snapshots = self._query_recording_snapshots(include_snapshots=False)

        if len(snapshots) == 0:
            return None

        distinct_id = snapshots[0]["distinct_id"]

        events_summary_by_window_id = self._get_events_summary_by_window_id(snapshots)

        if events_summary_by_window_id:
            # If all snapshots contain the new events_summary field...
            statsd.incr("session_recordings.metadata_parsed_from_events_summary")
            metadata = get_metadata_from_events_summary(events_summary_by_window_id)
        else:
            # ... otherwise use the legacy method
            snapshots = self._query_recording_snapshots(include_snapshots=True)
            statsd.incr("session_recordings.metadata_parsed_from_snapshot_data")
            metadata = self._get_metadata_from_snapshot_data(snapshots)

        metadata["distinct_id"] = cast(str, distinct_id)
        return metadata

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

        for window_id in events_summary_by_window_id:
            events_summary_by_window_id[window_id].sort(key=lambda x: x["timestamp"])

        # If any of the snapshots are missing the events_summary field, we fallback to the old parsing method
        if any(len(x) == 0 for x in events_summary_by_window_id.values()):
            return None

        return events_summary_by_window_id

    def _get_metadata_from_snapshot_data(self, snapshots: List[SessionRecordingEvent]) -> RecordingMetadata:
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

        return get_metadata_from_events_summary(events_summary_by_window_id)
