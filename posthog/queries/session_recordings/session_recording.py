from datetime import datetime, timedelta
from typing import List, Optional, TypedDict, Union

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.request import Request

from posthog.helpers.session_recording import SnapshotData, decompress_chunked_snapshot_data
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

    def _get_paginated_chunks(self):
        all_session_snapshots = self._query_recording_snapshots()
        has_next = False
        chunk_number = -1
        filtered_snapshots = []
        current_chunk_id = None
        for snapshot in all_session_snapshots:
            chunk_id = snapshot.snapshot_data.get("chunk_id")
            if not chunk_id:
                chunk_number += 1
            elif chunk_id != current_chunk_id:
                chunk_number += 1
                current_chunk_id = snapshot.snapshot_data.get("chunk_id")
            if chunk_number >= self._offset and chunk_number < self._offset + self._limit:
                filtered_snapshots.append(snapshot)
            elif chunk_number >= self._offset + self._limit:
                has_next = True
                break
        return (
            has_next,
            list(
                decompress_chunked_snapshot_data(
                    self._team.pk, self._session_recording_id, [s.snapshot_data for s in filtered_snapshots]
                )
            ),
        )

    def get_snapshots(self) -> RecordingSnapshots:
        has_next, snapshots = self._get_paginated_chunks()

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if has_next
            else None
        )

        return {
            "snapshots": snapshots,
            "next": next_url,
        }

    def _get_first_chunk_in_snapshot_list(self, snapshot_list):
        if len(snapshot_list) == 0:
            return []

        first_chunk_snapshots = []
        first_chunk_id = snapshot_list[0].snapshot_data.get("chunk_id")

        # Not chunked - can happen on old data on postgres instances with long retention policies
        if not first_chunk_id:
            first_chunk_snapshots.append(snapshot_list[0])
        else:
            for snapshot in snapshot_list:
                chunk_id = snapshot.snapshot_data.get("chunk_id")
                if chunk_id == first_chunk_id:
                    first_chunk_snapshots.append(snapshot)
                else:
                    break
        return list(
            decompress_chunked_snapshot_data(
                self._team.pk, self._session_recording_id, [s.snapshot_data for s in first_chunk_snapshots]
            )
        )

    def _get_first_and_last_chunk(self, all_recording_snapshots):
        first_chunk = self._get_first_chunk_in_snapshot_list(all_recording_snapshots)
        last_chunk = self._get_first_chunk_in_snapshot_list(list(reversed(all_recording_snapshots)))

        return (
            first_chunk,
            last_chunk,
        )

    def get_metadata(self) -> RecordingMetadata:
        all_snapshots = self._query_recording_snapshots()
        if len(all_snapshots) == 0:
            return {
                "start_time": None,
                "end_time": None,
                "duration": None,
                "session_id": None,
                "distinct_id": None,
            }

        first_chunk, last_chunk = self._get_first_and_last_chunk(all_snapshots)

        first_event = first_chunk[0]
        first_event_timestamp = datetime.fromtimestamp(first_event.get("timestamp") / 1000, timezone.utc)

        last_event = last_chunk[-1]
        last_event_timestamp = datetime.fromtimestamp(last_event.get("timestamp") / 1000, timezone.utc)

        first_snapshot = all_snapshots[0]

        return {
            "start_time": first_event_timestamp,
            "end_time": last_event_timestamp,
            "duration": last_event_timestamp - first_event_timestamp,
            "session_id": first_snapshot.session_id,
            "distinct_id": first_snapshot.distinct_id,
        }
