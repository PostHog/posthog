from datetime import datetime, timedelta
from typing import LiteralString, Optional

from django.conf import settings
from django.core.cache import cache

import pytz

from posthog.schema import HogQLQuery

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team
from posthog.session_recordings.models.metadata import RecordingBlockListing, RecordingMetadata

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
        existence = self._check_exists(session_id, team)

        if existence:
            # let's be cautious and not cache non-existence
            # in case we manage to check existence just before the first event hits ClickHouse
            # that should be impossible but cache invalidation is hard etc etc
            cache.set(cache_key, existence, timeout=seconds_until_midnight())
        return existence

    @staticmethod
    def _check_exists(session_id: str, team: Team) -> bool:
        result = sync_execute(
            """
            SELECT
                count(),
                min(min_first_timestamp) as start_time,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id = %(session_id)s
                AND min_first_timestamp <= %(python_now)s
            GROUP BY
                session_id
            HAVING
                expiry_time >= %(python_now)s
            """,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "ttl_days": ttl_days(team),
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        return result and result[0][0] > 0

    def sessions_found_with_timestamps(
        self, session_ids: list[str], team: Team
    ) -> tuple[set[str], Optional[datetime], Optional[datetime]]:
        """
        Check if sessions exist and return min/max timestamps for the entire list to optimize follow-up queries to get events for multiple sessions at once.
        Returns a tuple of (sessions_found, min_timestamp, max_timestamp).
        Timestamps are for the entire list of sessions, not per session.
        """
        if not session_ids:
            return set(), None, None
        # Check sessions within TTL
        found_sessions = self._find_with_timestamps(session_ids, team)
        if not found_sessions:
            return set(), None, None
        # Calculate min/max timestamps for the entire list of sessions and return
        sessions_found = {session_id for session_id, _, _ in found_sessions}
        min_timestamp = min(min_timestamp for _, min_timestamp, _ in found_sessions)
        max_timestamp = max(max_timestamp for _, _, max_timestamp in found_sessions)
        # Not searching for sessions outside of TTL to simplify logic
        return sessions_found, min_timestamp, max_timestamp

    @staticmethod
    def _find_with_timestamps(session_ids: list[str], team: Team) -> list[tuple[str, datetime, datetime]]:
        """
        Check which session IDs exist within the specified number of days.
        Returns a list of tuples of (session_id, min_timestamp, max_timestamp).
        Timestamps are per session, not for the entire list of sessions.
        """
        result = sync_execute(
            """
            SELECT
                session_id,
                min(min_first_timestamp) as min_timestamp,
                max(max_last_timestamp) as max_timestamp,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', min_timestamp) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id IN %(session_ids)s
                AND min_first_timestamp <= %(python_now)s
            GROUP BY
                session_id
            HAVING
                expiry_time >= %(python_now)s
            """,
            {
                "team_id": team.pk,
                "session_ids": session_ids,
                "ttl_days": ttl_days(team),
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        if not result:
            return []
        sessions_found: list[tuple[str, datetime, datetime]] = [(row[0], row[1], row[2]) for row in result]
        return sessions_found

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
                groupArrayArray(block_urls) as block_urls,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time,
                dateDiff('DAY', toDateTime(%(python_now)s), expiry_time) as recording_ttl
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id = %(session_id)s
                AND min_first_timestamp <= %(python_now)s
                {optional_timestamp_clause}
            GROUP BY
                session_id
            HAVING
                expiry_time >= %(python_now)s
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
        format: Optional[str] = None,
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
                    groupArrayArray(block_urls) as block_urls,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time
                FROM
                    session_replay_events
                PREWHERE
                    team_id = %(team_id)s
                    AND session_id = %(session_id)s
                    AND min_first_timestamp <= %(python_now)s
                    {optional_timestamp_clause}
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= %(python_now)s
                {optional_format_clause}
                """
        query = query.format(
            optional_timestamp_clause=(
                "AND min_first_timestamp >= %(recording_start_time)s" if recording_start_time else ""
            ),
            optional_format_clause=(f"FORMAT {format}" if format else ""),
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
            retention_period_days=replay[16],
            expiry_time=replay[17],
            recording_ttl=replay[18],
        )

    def get_metadata(
        self,
        session_id: str,
        team: Team,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingMetadata]:
        query = self.get_metadata_query(recording_start_time)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.now(pytz.timezone("UTC")),
                "ttl_days": ttl_days(team),
            },
        )
        recording_metadata = self.build_recording_metadata(session_id, replay_response)
        return recording_metadata

    def get_group_metadata(
        self,
        session_ids: list[str],
        team: Team,
        recordings_min_timestamp: Optional[datetime] = None,
        recordings_max_timestamp: Optional[datetime] = None,
    ) -> dict[str, Optional[RecordingMetadata]]:
        """
        Get metadata for a group of sessions in one call.
        """
        if not session_ids:
            return {}

        # Minimal timestamp in the recordings provided
        optional_min_timestamp_clause = (
            "AND min_first_timestamp >= %(recordings_min_timestamp)s" if recordings_min_timestamp else ""
        )
        # Maximal timestamp in the recordings provided
        optional_max_timestamp_clause = (
            "AND min_first_timestamp <= %(recordings_max_timestamp)s" if recordings_max_timestamp else ""
        )
        # Get data from DB
        query = f"""
            SELECT
                session_id,
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
                groupArrayArray(block_urls) as block_urls,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time,
                dateDiff('DAY', toDateTime(%(python_now)s), expiry_time) as recording_ttl
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id IN %(session_ids)s
                {optional_max_timestamp_clause if recordings_max_timestamp else "AND min_first_timestamp <= %(python_now)s"}
                {optional_min_timestamp_clause}
            GROUP BY
                session_id
            HAVING
                expiry_time >= %(python_now)s
        """
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_ids": session_ids,
                "recordings_min_timestamp": recordings_min_timestamp,
                "recordings_max_timestamp": recordings_max_timestamp,
                "python_now": datetime.now(pytz.timezone("UTC")),
                "ttl_days": ttl_days(team),
            },
        )
        # Build metadata for each session
        result: dict[str, Optional[RecordingMetadata]] = {session_id: None for session_id in session_ids}
        for row in replay_response:
            # Match build_recording_metadata's expected format
            session_id = row[0]
            session_data = [row[1:]]
            metadata = self.build_recording_metadata(session_id, session_data)
            if metadata:
                result[session_id] = metadata
        return result

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
        ttl_days: Optional[int] = None,
    ) -> Optional[RecordingBlockListing]:
        query = self.get_block_listing_query(recording_start_time)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.now(pytz.timezone("UTC")),
                "ttl_days": ttl_days or 365,
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

    @staticmethod
    def get_sessions_from_distinct_id_query(
        format: Optional[str] = None,
    ):
        """
        Helper function to build a query for listing all session IDs for a given set of distinct IDs
        """
        query = """
                SELECT
                    session_id,
                    min(min_first_timestamp) as start_time,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time
                FROM
                    session_replay_events
                PREWHERE
                    team_id = %(team_id)s
                    AND distinct_id IN (%(distinct_ids)s)
                    AND min_first_timestamp <= %(python_now)s
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= %(python_now)s
                {optional_format_clause}
                """
        query = query.format(
            optional_format_clause=(f"FORMAT {format}" if format else ""),
        )
        return query

    @staticmethod
    def get_soon_to_expire_sessions_query(
        format: Optional[str] = None,
    ):
        """
        Helper function to build a query for listing all sessions that are about to expire
        """
        query = """
                SELECT
                    session_id,
                    min(min_first_timestamp) as start_time,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, %(ttl_days)s)) as expiry_time,
                    dateDiff('DAY', toDateTime(%(python_now)s), expiry_time) as recording_ttl
                FROM
                    session_replay_events
                PREWHERE
                    team_id = %(team_id)s
                    AND min_first_timestamp <= %(python_now)s
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= %(python_now)s
                    AND recording_ttl <= %(ttl_threshold)s
                ORDER BY recording_ttl ASC
                LIMIT %(limit)s
                {optional_format_clause}
                """
        query = query.format(
            optional_format_clause=(f"FORMAT {format}" if format else ""),
        )
        return query


def ttl_days(team: Team) -> int:
    if is_cloud():
        # NOTE: We use file export as a proxy to see if they are subbed to Recordings
        is_paid = team.organization.is_feature_available(AvailableFeature.RECORDINGS_FILE_EXPORT)
        ttl_days = settings.REPLAY_RETENTION_DAYS_MAX if is_paid else settings.REPLAY_RETENTION_DAYS_MIN
    else:
        ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7

    return ttl_days
