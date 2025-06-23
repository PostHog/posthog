from datetime import datetime, timedelta
from typing import LiteralString, Optional

import pytz
from django.conf import settings
from django.core.cache import cache

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature

from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team
from posthog.schema import HogQLQuery
from posthog.session_recordings.models.metadata import (
    RecordingMetadata,
    RecordingBlockListing,
)

DEFAULT_EVENT_FIELDS = [
    "event",
    "timestamp",
    "elements_chain_href",
    "elements_chain_texts",
    "elements_chain_elements",
    "properties.$window_id",
    "properties.$current_url",
    "properties.$event_type",
]


def seconds_until_midnight():
    now = datetime.now(pytz.timezone("UTC"))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    difference = midnight - now
    return difference.seconds


class SessionReplayEvents:
    def exists(self, session_id: str, team: Team) -> bool:
        cache_key = f"summarize_recording_existence_team_{team.pk}_id_{session_id}"
        cached_response = cache.get(cache_key)
        if isinstance(cached_response, bool):
            return cached_response

        # Once we know that session exists we don't need to check again (until the end of the day since TTL might apply)
        existence = self._check_exists_within_days(ttl_days(team), session_id, team) or self._check_exists_within_days(
            370, session_id, team
        )

        if existence:
            # let's be cautious and not cache non-existence
            # in case we manage to check existence just before the first event hits ClickHouse
            # that should be impossible but cache invalidation is hard etc etc
            cache.set(cache_key, existence, timeout=seconds_until_midnight())
        return existence

    @staticmethod
    def _check_exists_within_days(days: int, session_id: str, team: Team) -> bool:
        result = sync_execute(
            """
            SELECT count()
            FROM session_replay_events
            PREWHERE team_id = %(team_id)s
            AND session_id = %(session_id)s
            AND min_first_timestamp >= now() - INTERVAL %(days)s DAY
            AND min_first_timestamp <= now()
            """,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "days": days,
            },
        )
        return result[0][0] > 0

    @staticmethod
    def get_metadata_query(
        recording_start_time: Optional[datetime] = None,
    ) -> LiteralString:
        """
        Helper function to build a query for session metadata, to be able to use
        both in production and locally (for example, when testing session summary)
        """
        query = """
            SELECT
                any(distinct_id),
                min(min_first_timestamp) as start_time,
                max(max_last_timestamp) as end_time,
                dateDiff('SECOND', start_time, end_time) as duration,
                argMinMerge(first_url) as first_url,
                sum(click_count),
                sum(keypress_count),
                sum(mouse_activity_count),
                sum(active_milliseconds)/1000 as active_seconds,
                sum(console_log_count) as console_log_count,
                sum(console_warn_count) as console_warn_count,
                sum(console_error_count) as console_error_count,
                argMinMerge(snapshot_source) as snapshot_source,
                groupArrayArray(block_first_timestamps) as block_first_timestamps,
                groupArrayArray(block_last_timestamps) as block_last_timestamps,
                groupArrayArray(block_urls) as block_urls
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id = %(session_id)s
                AND min_first_timestamp <= %(python_now)s
                {optional_timestamp_clause}
            GROUP BY
                session_id
        """
        query = query.format(
            optional_timestamp_clause=(
                "AND min_first_timestamp >= %(recording_start_time)s" if recording_start_time else ""
            )
        )
        return query

    @staticmethod
    def get_block_listing_query(
        recording_start_time: Optional[datetime] = None,
    ) -> LiteralString:
        """
        Helper function to build a query for session metadata, to be able to use
        both in production and locally (for example, when testing session summary)
        """
        query = """
                SELECT
                    min(min_first_timestamp) as start_time,
                    groupArrayArray(block_first_timestamps) as block_first_timestamps,
                    groupArrayArray(block_last_timestamps) as block_last_timestamps,
                    groupArrayArray(block_urls) as block_urls
                FROM
                    session_replay_events
                    PREWHERE
                    team_id = %(team_id)s
                    AND session_id = %(session_id)s
                    AND min_first_timestamp <= %(python_now)s
                    {optional_timestamp_clause}
                GROUP BY
                    session_id
                """
        query = query.format(
            optional_timestamp_clause=(
                "AND min_first_timestamp >= %(recording_start_time)s" if recording_start_time else ""
            )
        )
        return query

    @staticmethod
    def build_recording_metadata(session_id: str, replay_response: list[tuple]) -> Optional[RecordingMetadata]:
        if len(replay_response) == 0:
            return None
        if len(replay_response) > 1:
            raise ValueError("Multiple sessions found for session_id: {}".format(session_id))
        replay = replay_response[0]
        return RecordingMetadata(
            distinct_id=replay[0],
            start_time=replay[1],
            end_time=replay[2],
            duration=replay[3],
            first_url=replay[4],
            click_count=replay[5],
            keypress_count=replay[6],
            mouse_activity_count=replay[7],
            active_seconds=replay[8],
            console_log_count=replay[9],
            console_warn_count=replay[10],
            console_error_count=replay[11],
            snapshot_source=replay[12] or "web",
            block_first_timestamps=replay[13],
            block_last_timestamps=replay[14],
            block_urls=replay[15],
        )

    def get_metadata(
        self,
        session_id: str,
        team_id: int,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingMetadata]:
        query = self.get_metadata_query(recording_start_time)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team_id,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        recording_metadata = self.build_recording_metadata(session_id, replay_response)
        return recording_metadata

    @staticmethod
    def build_recording_block_listing(session_id: str, replay_response: list[tuple]) -> Optional[RecordingBlockListing]:
        if len(replay_response) == 0:
            return None
        if len(replay_response) > 1:
            raise ValueError("Multiple sessions found for session_id: {}".format(session_id))

        replay = replay_response[0]

        return RecordingBlockListing(
            start_time=replay[0],
            block_first_timestamps=replay[1],
            block_last_timestamps=replay[2],
            block_urls=replay[3],
        )

    def list_blocks(
        self,
        session_id: str,
        team: Team,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingBlockListing]:
        query = self.get_block_listing_query(recording_start_time)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        recording_metadata = self.build_recording_block_listing(session_id, replay_response)
        return recording_metadata

    def get_events_query(
        self,
        session_id: str,
        metadata: RecordingMetadata,
        # Optional, to avoid modifying the existing behavior
        events_to_ignore: list[str] | None = None,
        extra_fields: list[str] | None = None,
        limit: int | None = None,
        page: int = 0,
    ) -> HogQLQuery:
        """
        Helper function to build a HogQLQuery for session events, to be able to use
        both in production and locally (for example, when testing session summary)
        """
        fields = [*DEFAULT_EVENT_FIELDS]
        if extra_fields:
            fields.extend(extra_fields)
        q = f"SELECT {', '.join(fields)} FROM events"
        q += """
            WHERE timestamp >= {start_time} AND timestamp <= {end_time}
            AND $session_id = {session_id}
            """
        # Avoid events adding little context, like feature flag calls
        if events_to_ignore:
            q += " AND event NOT IN {events_to_ignore}"
        q += " ORDER BY timestamp ASC"
        # Pagination to allow consuming more than default 100 rows per call
        if limit is not None and limit > 0:
            q += " LIMIT {limit}"
            # Offset makes sense only if limit is defined,
            # to avoid mixing default HogQL limit and the expected one
            if page > 0:
                q += " OFFSET {offset}"
        hq = HogQLQuery(
            query=q,
            values={
                # Add some wiggle room to the timings, to ensure we get all the events
                # The time range is only to stop CH loading too much data to find the session
                "start_time": metadata["start_time"] - timedelta(seconds=100),
                "end_time": metadata["end_time"] + timedelta(seconds=100),
                "session_id": session_id,
                "events_to_ignore": events_to_ignore,
                "limit": limit,
                "offset": page * limit if limit is not None else 0,
            },
        )
        return hq

    def get_events(
        self,
        session_id: str,
        team: Team,
        metadata: RecordingMetadata,
        # Optional, to avoid modifying the existing behavior
        events_to_ignore: list[str] | None = None,
        extra_fields: list[str] | None = None,
        limit: int | None = None,
        page: int = 0,
    ) -> tuple[list | None, list | None]:
        from posthog.schema import HogQLQueryResponse
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        hq = self.get_events_query(session_id, metadata, events_to_ignore, extra_fields, limit, page)
        result: HogQLQueryResponse = HogQLQueryRunner(
            team=team,
            query=hq,
        ).calculate()
        return result.columns, result.results

    def get_events_for_session(self, session_id: str, team: Team, limit: int = 100) -> list[dict]:
        """Get all events for a session."""
        query = """
            SELECT event, timestamp
            FROM events
            WHERE team_id = %(team_id)s
            AND $session_id = %(session_id)s
            ORDER BY timestamp ASC
            LIMIT %(limit)s
        """

        events = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "limit": limit,
            },
        )
        return [{"event": e[0], "timestamp": e[1]} for e in events]

    def get_similar_recordings(
        self, session_id: str, team: Team, limit: int = 10, similarity_range: float = 0.5
    ) -> list[dict]:
        """Find recordings with similar URL sequences.
        Args:
            session_id: The session ID to find similar recordings for
            team: The team the recording belongs to
            limit: Maximum number of similar recordings to return
            similarity_range: How similar the recordings should be (0.0 to 1.0)
        """
        query = """
        WITH target_urls AS (
            SELECT groupArrayArray(all_urls) as url_sequence
            FROM session_replay_events
            WHERE team_id = %(team_id)s
            AND session_id = %(session_id)s
        )
        SELECT
            sre.session_id,
            sre.distinct_id,
            min_first_timestamp as start_time,
            max_last_timestamp as end_time,
            click_count,
            keypress_count,
            mouse_activity_count,
            active_milliseconds,
            all_urls as urls,
            target_urls.url_sequence
        FROM session_replay_events sre
        CROSS JOIN target_urls
        WHERE sre.team_id = %(team_id)s
        AND sre.session_id != %(session_id)s
        GROUP BY
            sre.session_id,
            sre.distinct_id,
            min_first_timestamp,
            max_last_timestamp,
            click_count,
            keypress_count,
            mouse_activity_count,
            active_milliseconds,
            all_urls,
            target_urls.url_sequence
        HAVING
            length(urls) > 0 AND
            urls = url_sequence
        LIMIT %(limit)s
        """

        results = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "limit": limit,
            },
        )

        return [
            {
                "session_id": r[0],
                "distinct_id": r[1],
                "start_time": r[2],
                "end_time": r[3],
                "click_count": r[4],
                "keypress_count": r[5],
                "mouse_activity_count": r[6],
                "active_milliseconds": r[7],
                "urls": r[8],
            }
            for r in results
        ]


def ttl_days(team: Team) -> int:
    if is_cloud():
        # NOTE: We use file export as a proxy to see if they are subbed to Recordings
        is_paid = team.organization.is_feature_available(AvailableFeature.RECORDINGS_FILE_EXPORT)
        ttl_days = settings.REPLAY_RETENTION_DAYS_MAX if is_paid else settings.REPLAY_RETENTION_DAYS_MIN
    else:
        ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7

    return ttl_days
