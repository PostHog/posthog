from typing import Any, Dict, List, Tuple, Union

from django.db import connection
from django.db.models import QuerySet
from rest_framework.request import Request

from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.utils import namedtuplefetchall
from posthog.utils import format_query_params_absolute_url

DistinctId = str
Snapshots = List[Any]
Events = Tuple[str, str, Snapshots]


RECORDINGS_NUM_CHUNKS_LIMIT = 20  # Should be tuned to find the best value


class SessionRecordingSnapshots:
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
        self._limit = self._filter.limit if self._filter.limit else RECORDINGS_NUM_CHUNKS_LIMIT
        self._offset = self._filter.offset if self._filter.offset else 0

    def query_recording_snapshots(self) -> Union[QuerySet, List[SessionRecordingEvent]]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    def get_paginated_chunks(self):
        all_session_snapshots = self.query_recording_snapshots()
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

    def run(self) -> Dict[str, Any]:
        has_next, snapshots = self.get_paginated_chunks()

        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if has_next
            else None
        )

        return {
            "snapshots": snapshots,
            "next": next_url,
        }


class SessionRecordingMetaData:
    _request: Request
    _session_recording_id: str
    _team: Team

    def __init__(self, request: Request, session_recording_id: str, team: Team) -> None:
        self._request = request
        self._session_recording_id = session_recording_id
        self._team = team

    _recording_metadata_query = """
            SELECT
                count(*) as event_count,
                MIN(distinct_id) as distinct_id,
                MIN(timestamp) AS start_time,
                MAX(timestamp) AS end_time,
                EXTRACT(EPOCH FROM MAX(timestamp) - MIN(timestamp)) as duration
            FROM posthog_sessionrecordingevent
            WHERE
                team_id = %(team_id)s
                AND session_id = %(session_recording_id)s
    """

    def run(self, *args, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute(
                self._recording_metadata_query,
                {"team_id": self._team.pk, "session_recording_id": self._session_recording_id},
            )
            query_results = namedtuplefetchall(cursor)
        result = query_results[0]._asdict()

        return result
