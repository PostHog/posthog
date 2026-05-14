from typing import Any

from posthog.schema import (
    CachedRecordingsQueryResponse,
    RecordingsQuery,
    RecordingsQueryResponse,
    SessionRecordingType,
    SnapshotSource,
)

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery


class RecordingsQueryRunner(AnalyticsQueryRunner[RecordingsQueryResponse]):
    query: RecordingsQuery
    cached_response: CachedRecordingsQueryResponse

    def _calculate(self) -> RecordingsQueryResponse:
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY)

        listing = SessionRecordingListFromQuery(
            team=self.team,
            query=self.query,
            hogql_query_modifiers=self.modifiers,
        )
        result = listing.run()

        recordings = [self._map_recording(row) for row in result.results]

        return RecordingsQueryResponse(
            results=recordings,
            has_next=result.has_more_recording,
            next_cursor=result.next_cursor,
        )

    def to_query(self):
        listing = SessionRecordingListFromQuery(
            team=self.team,
            query=self.query,
            hogql_query_modifiers=self.modifiers,
        )
        return listing.get_query()

    @staticmethod
    def _map_recording(row: dict[str, Any]) -> SessionRecordingType:
        start_time = row["start_time"]
        end_time = row["end_time"]

        return SessionRecordingType(
            id=row["session_id"],
            distinct_id=row.get("distinct_id"),
            start_time=start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time),
            end_time=end_time.isoformat() if hasattr(end_time, "isoformat") else str(end_time),
            recording_duration=row["duration"],
            active_seconds=row.get("active_seconds"),
            inactive_seconds=row.get("inactive_seconds"),
            click_count=row.get("click_count"),
            keypress_count=row.get("keypress_count"),
            mouse_activity_count=row.get("mouse_activity_count"),
            console_log_count=row.get("console_log_count"),
            console_warn_count=row.get("console_warn_count"),
            console_error_count=row.get("console_error_count"),
            start_url=row.get("first_url"),
            activity_score=row.get("activity_score"),
            ongoing=row.get("ongoing"),
            recording_ttl=row.get("recording_ttl"),
            retention_period_days=row.get("retention_period_days"),
            # These fields require Postgres enrichment which the query runner skips.
            # Sensible defaults match Max AI's approach in filter_session_recordings.py.
            viewed=False,
            viewers=[],
            snapshot_source=SnapshotSource.WEB,
        )
