from datetime import datetime, timedelta
from typing import LiteralString, Optional

from django.core.cache import cache

import pytz

from posthog.schema import HogQLQuery

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Product, tag_queries
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
        tag_queries(product=Product.REPLAY, team_id=team.pk)
        result = sync_execute(
            """
            SELECT
                count(),
                min(min_first_timestamp) as start_time,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
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
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        return result and result[0][0] > 0

    def sessions_found_with_timestamps(
        self, session_ids: list[str], team: Team
    ) -> tuple[set[str], Optional[datetime], Optional[datetime]]:
        """
        Check if sessions exist in both session_replay_events and events tables.
        Returns a tuple of (sessions_found, min_timestamp, max_timestamp).
        Timestamps are for the entire list of sessions, not per session.
        Sessions must exist in both tables to be included in the result.
        """
        if not session_ids:
            return set(), None, None
        # Check sessions within TTL in session_replay_events
        found_sessions = self._find_with_timestamps(session_ids, team)
        if not found_sessions:
            return set(), None, None
        # Calculate min/max timestamps for the entire list of sessions
        replay_session_ids = [session_id for session_id, _, _ in found_sessions]
        min_timestamp = min(ts for _, ts, _ in found_sessions)
        max_timestamp = max(ts for _, _, ts in found_sessions)
        # Check which sessions also have events in the events table
        sessions_with_events = self._find_sessions_in_events(replay_session_ids, min_timestamp, max_timestamp, team)
        if not sessions_with_events:
            return set(), None, None
        # Filter to only sessions that exist in both tables
        session_ids_found = {session_id for session_id, _, _ in found_sessions if session_id in sessions_with_events}
        if not session_ids_found:
            return set(), None, None
        # Recalculate timestamps for filtered sessions only
        min_timestamp = min(ts for session_id, ts, _ in found_sessions if session_id in session_ids_found)
        max_timestamp = max(ts for session_id, _, ts in found_sessions if session_id in session_ids_found)
        return session_ids_found, min_timestamp, max_timestamp

    @staticmethod
    def _find_with_timestamps(session_ids: list[str], team: Team) -> list[tuple[str, datetime, datetime]]:
        """
        Check which session IDs exist in session_replay_events within retention period.
        Returns a list of tuples of (session_id, min_timestamp, max_timestamp).
        Timestamps are per session, not for the entire list of sessions.
        """
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        now = datetime.now(pytz.timezone("UTC"))
        query = HogQLQuery(
            query="""
                SELECT
                    session_id,
                    min(min_first_timestamp) as min_timestamp,
                    max(max_last_timestamp) as max_timestamp,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('day', min_timestamp) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
                FROM
                    raw_session_replay_events
                WHERE
                    session_id IN {session_ids}
                    AND min_first_timestamp <= {now}
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= {now}
            """,
            values={
                "session_ids": session_ids,
                "now": now,
            },
        )
        tag_queries(product=Product.REPLAY, team_id=team.pk)
        result = HogQLQueryRunner(team=team, query=query).calculate()
        if not result.results:
            return []
        sessions_found: list[tuple[str, datetime, datetime]] = [(row[0], row[1], row[2]) for row in result.results]
        return sessions_found

    @staticmethod
    def _find_sessions_in_events(
        session_ids: list[str], min_timestamp: datetime, max_timestamp: datetime, team: Team
    ) -> set[str]:
        """
        Check which session IDs have events in the events table within the given time range.
        Returns a set of session IDs that have at least one event.
        """
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        query = HogQLQuery(
            query="""
                SELECT DISTINCT properties.$session_id AS session_id
                FROM events
                WHERE properties.$session_id IN {session_ids}
                    AND timestamp >= {min_timestamp}
                    AND timestamp <= {max_timestamp}
            """,
            values={
                "session_ids": session_ids,
                "min_timestamp": min_timestamp,
                "max_timestamp": max_timestamp,
            },
        )
        tag_queries(product=Product.REPLAY, team_id=team.pk)
        result = HogQLQueryRunner(team=team, query=query).calculate()
        if not result.results:
            return set()
        return {row[0] for row in result.results}

    @staticmethod
    def get_metadata_query(
        recording_start_time: Optional[datetime] = None,
        format: Optional[str] = None,
    ) -> LiteralString:
        """
        Helper function to build a query for session metadata, to be able to use
        both in production and locally (for example, when testing session summary)
        """
        query = """
            SELECT
                session_id,
                any(distinct_id) as distinct_id,
                min(min_first_timestamp) as start_time,
                max(max_last_timestamp) as end_time,
                dateDiff('SECOND', start_time, end_time) as duration,
                argMinMerge(first_url) as first_url,
                sum(click_count) as click_count,
                sum(keypress_count) as keypress_count,
                sum(mouse_activity_count) as mouse_activity_count,
                sum(active_milliseconds)/1000 as active_seconds,
                sum(console_log_count) as console_log_count,
                sum(console_warn_count) as console_warn_count,
                sum(console_error_count) as console_error_count,
                argMinMerge(snapshot_source) as snapshot_source,
                argMinMerge(snapshot_library) as snapshot_library,
                groupArrayArray(block_first_timestamps) as block_first_timestamps,
                groupArrayArray(block_last_timestamps) as block_last_timestamps,
                groupArrayArray(block_urls) as block_urls,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time,
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
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
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
            distinct_id=replay[1],
            start_time=replay[2],
            end_time=replay[3],
            duration=replay[4],
            first_url=replay[5],
            click_count=replay[6],
            keypress_count=replay[7],
            mouse_activity_count=replay[8],
            active_seconds=replay[9],
            console_log_count=replay[10],
            console_warn_count=replay[11],
            console_error_count=replay[12],
            snapshot_source=replay[13] or "web",
            snapshot_library=replay[14],
            block_first_timestamps=replay[15],
            block_last_timestamps=replay[16],
            block_urls=replay[17],
            retention_period_days=replay[18],
            expiry_time=replay[19],
            recording_ttl=replay[20],
        )

    def get_metadata(
        self,
        session_id: str,
        team: Team,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingMetadata]:
        query = self.get_metadata_query(recording_start_time)
        tag_queries(product=Product.REPLAY, team_id=team.pk)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
                "python_now": datetime.now(pytz.timezone("UTC")),
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
                any(distinct_id) as distinct_id,
                min(min_first_timestamp) as start_time,
                max(max_last_timestamp) as end_time,
                dateDiff('SECOND', start_time, end_time) as duration,
                argMinMerge(first_url) as first_url,
                sum(click_count) as click_count,
                sum(keypress_count) as keypress_count,
                sum(mouse_activity_count) as mouse_activity_count,
                sum(active_milliseconds)/1000 as active_seconds,
                sum(console_log_count) as console_log_count,
                sum(console_warn_count) as console_warn_count,
                sum(console_error_count) as console_error_count,
                argMinMerge(snapshot_source) as snapshot_source,
                argMinMerge(snapshot_library) as snapshot_library,
                groupArrayArray(block_first_timestamps) as block_first_timestamps,
                groupArrayArray(block_last_timestamps) as block_last_timestamps,
                groupArrayArray(block_urls) as block_urls,
                max(retention_period_days) as retention_period_days,
                dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time,
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
        tag_queries(product=Product.REPLAY, team_id=team.pk)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_ids": session_ids,
                "recordings_min_timestamp": recordings_min_timestamp,
                "recordings_max_timestamp": recordings_max_timestamp,
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        # Build metadata for each session
        result: dict[str, Optional[RecordingMetadata]] = dict.fromkeys(session_ids)
        for row in replay_response:
            session_id = row[0]
            metadata = self.build_recording_metadata(session_id, [row])
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
    ) -> Optional[RecordingBlockListing]:
        query = self.get_block_listing_query(recording_start_time)
        tag_queries(product=Product.REPLAY, team_id=team.pk)
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
        tag_queries(product=Product.REPLAY, team_id=team.pk)
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
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
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
    def get_sessions_from_team_id_query(
        format: Optional[str] = None,
    ):
        """
        Helper function to build a query for listing all session IDs for a given team ID
        """
        query = """
                SELECT
                    session_id,
                    min(min_first_timestamp) as start_time,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
                FROM
                    session_replay_events
                PREWHERE
                    team_id = %(team_id)s
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
    def count_soon_to_expire_sessions_query(
        format: Optional[str] = None,
    ):
        """
        Helper function to build a query for counting all sessions that are about to expire
        """
        query = """
                WITH
                    expiring_sessions
                AS (
                    SELECT
                        session_id,
                        min(min_first_timestamp) as start_time,
                        max(retention_period_days) as retention_period_days,
                        dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time,
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
                )
                SELECT
                    count(session_id) as recording_count
                FROM expiring_sessions
                {optional_format_clause}
                """
        query = query.format(
            optional_format_clause=(f"FORMAT {format}" if format else ""),
        )
        return query


def get_person_emails_for_session_ids(
    session_ids: list[str],
    min_timestamp: datetime,
    max_timestamp: datetime,
    team_id: int,
) -> dict[str, str | None]:
    """
    Get person emails for a list of session IDs.
    """
    from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

    if not session_ids:
        return {}
    if len(session_ids) > 1000:
        raise ValueError(f"Cannot query more than 1000 session IDs at once, got {len(session_ids)}")
    if (max_timestamp - min_timestamp).days > 90:
        raise ValueError(
            f"Date range cannot exceed 3 months (90 days), got {(max_timestamp - min_timestamp).days} days"
        )
    team = Team.objects.get(pk=team_id)
    query = HogQLQuery(
        query="""
            SELECT
                properties.$session_id AS session_id,
                any(person.properties.email) AS email
            FROM events
            WHERE properties.$session_id IN {session_ids}
                AND timestamp >= {min_timestamp}
                AND timestamp <= {max_timestamp}
            GROUP BY properties.$session_id
        """,
        values={
            "session_ids": session_ids,
            "min_timestamp": min_timestamp,
            "max_timestamp": max_timestamp,
        },
    )
    tag_queries(product=Product.REPLAY, team_id=team_id)
    result = HogQLQueryRunner(team=team, query=query).calculate()
    email_mapping: dict[str, str | None] = dict.fromkeys(session_ids)
    if result.results:
        for row in result.results:
            session_id = row[0]
            email = row[1]
            if email and isinstance(email, str) and email.strip():
                email_mapping[session_id] = email
            else:
                email_mapping[session_id] = None
    return email_mapping
