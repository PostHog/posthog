import re
import json
from datetime import datetime, timedelta
from typing import Optional

from django.core.cache import cache

import pytz

from posthog.schema import HogQLQuery

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.session_recordings.models.metadata import RecordingMetadata

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

_UUIDV7_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# The session id's embedded timestamp comes from the client clock while
# min_first_timestamp is ingestion-derived, so allow generous slack either side.
SESSION_ID_CLOCK_SKEW_SLACK = timedelta(days=3)

_EARLIEST_PLAUSIBLE_SESSION_START = datetime(2020, 1, 1, tzinfo=pytz.UTC)


def uuidv7_session_lower_bound(session_id: str, now: datetime | None = None) -> datetime | None:
    """A safe ``min_first_timestamp`` lower bound derived from a UUIDv7 session id.

    The session_replay_events sort key is (toDate(min_first_timestamp), team_id, session_id),
    so a session lookup without a date lower bound walks index granules across the table's
    entire retained date range. SDK session ids are UUIDv7 — their first 48 bits encode the
    session start in ms — which lets us bound the scan without callers having to know the
    recording's start time. Returns None (no bound, today's behavior) for ids that don't
    parse or whose embedded timestamp is implausible (badly skewed client clocks exist).
    """
    if not _UUIDV7_SESSION_ID.match(session_id):
        return None
    embedded_ms = int(session_id.replace("-", "")[:12], 16)
    now = now or datetime.now(pytz.UTC)
    # ms-level precheck: fromtimestamp raises OverflowError/ValueError on
    # far-future values (48 bits reach the year 10889).
    if embedded_ms > (now + timedelta(days=1)).timestamp() * 1000:
        return None
    embedded_start = datetime.fromtimestamp(embedded_ms / 1000, tz=pytz.UTC)
    if embedded_start < _EARLIEST_PLAUSIBLE_SESSION_START:
        return None
    return embedded_start - SESSION_ID_CLOCK_SKEW_SLACK


# Wide window for capture diagnostics when the session id carries no usable
# timestamp (or the bounded window missed): covers the longest replay retention
# plan plus slack, so any recording that can still be played can be diagnosed.
CAPTURE_DIAGNOSTICS_FALLBACK_LOOKBACK = timedelta(days=370)


# The capture diagnostics panel only interprets recording-diagnostic properties
# (see frontend replayCaptureDiagnostics.ts); the response is filtered to these
# so replay viewers don't receive arbitrary event properties through this endpoint.
_DIAGNOSTIC_PROPERTY_PREFIX = "$sdk_debug_"
_DIAGNOSTIC_PROPERTIES = frozenset(
    {
        "$has_recording",
        "$recording_status",
        "$replay_minimum_duration",
        "$replay_sample_rate",
        "$session_recording_remote_config",
        "$session_recording_start_reason",
        "$session_recording_url_trigger_activated_session",
        "$session_recording_url_trigger_status",
    }
)


def _filter_to_diagnostic_properties(properties: dict) -> dict:
    return {
        key: value
        for key, value in properties.items()
        if key in _DIAGNOSTIC_PROPERTIES or key.startswith(_DIAGNOSTIC_PROPERTY_PREFIX)
    }


def get_latest_session_event_properties(session_id: str, team: Team) -> Optional[dict]:
    """The most recent event's recording-diagnostic properties for a session, for the capture diagnostics panel.

    Bounded by a window derived from the UUIDv7 session id so the events sort key
    can prune the scan; misses (or ids that don't parse) fall back to a
    retention-wide window so a skewed client clock degrades to a slower lookup
    rather than missing diagnostics. Deliberate trade-off: when a session has
    events both inside and outside the bounded window, the in-window latest wins
    without consulting the fallback.
    """
    lower_bound = uuidv7_session_lower_bound(session_id)
    if lower_bound is not None:
        # lower_bound is embedded_start - slack; sessions last at most a day,
        # so embedded_start + 1d + slack closes the window symmetrically.
        upper_bound = lower_bound + 2 * SESSION_ID_CLOCK_SKEW_SLACK + timedelta(days=1)
        properties = _latest_session_event_properties_between(session_id, team, lower_bound, upper_bound)
        if properties is not None:
            return properties
    now = datetime.now(pytz.UTC)
    return _latest_session_event_properties_between(
        session_id, team, now - CAPTURE_DIAGNOSTICS_FALLBACK_LOOKBACK, now + timedelta(days=1)
    )


def _latest_session_event_properties_between(
    session_id: str, team: Team, date_from: datetime, date_to: datetime
) -> Optional[dict]:
    from posthog.hogql_queries.hogql_query_runner import (
        HogQLQueryRunner,  # noqa: PLC0415 — breaks a circular import, matching this file's other HogQLQueryRunner imports
    )

    query = HogQLQuery(
        query="""
            SELECT properties
            FROM events
            WHERE $session_id = {session_id}
                AND timestamp >= {date_from}
                AND timestamp <= {date_to}
            ORDER BY timestamp DESC
            LIMIT 1
        """,
        values={"session_id": session_id, "date_from": date_from, "date_to": date_to},
    )
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
    result = HogQLQueryRunner(team=team, query=query).calculate()
    if not result.results:
        return None
    row = result.results[0][0]
    if not row:
        return None
    return _filter_to_diagnostic_properties(json.loads(row) if isinstance(row, str) else row)


def seconds_until_midnight():
    now = datetime.now(pytz.timezone("UTC"))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    difference = midnight - now
    return difference.seconds


class SessionReplayEvents:
    def exists(self, session_id: str, team: Team) -> bool:
        cache_key = f"session_recording_existence_team_{team.pk}_id_{session_id}"
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

    def batch_exists(self, session_ids: list[str], team: Team) -> dict[str, bool]:
        """
        Check which session IDs have recordings within retention period.
        Returns a dict mapping session_id -> exists (boolean).
        Only positive results (exists=True) are cached.
        """
        if not session_ids:
            return {}

        results: dict[str, bool] = {}
        uncached_session_ids: list[str] = []

        # Check cache first
        for sid in session_ids:
            cache_key = f"session_recording_existence_team_{team.pk}_id_{sid}"
            cached_value = cache.get(cache_key)
            if cached_value is True:
                results[sid] = True
            else:
                uncached_session_ids.append(sid)

        if not uncached_session_ids:
            return results

        # Query ClickHouse for uncached session IDs
        found_sessions = self._find_with_timestamps(uncached_session_ids, team)
        # Build a mapping from session_id to expiry_time (tuple is: session_id, min_ts, max_ts, expiry_time)
        session_expiry_map = {session_id: expiry_time for session_id, _, _, expiry_time in found_sessions}

        now = datetime.now(pytz.timezone("UTC"))

        # Build results and cache positive results with expiry-based TTL
        for sid in uncached_session_ids:
            exists = sid in session_expiry_map
            results[sid] = exists
            if exists:
                expiry_time = session_expiry_map[sid]
                ttl_seconds = int((expiry_time - now).total_seconds())
                if ttl_seconds > 0:
                    cache_key = f"session_recording_existence_team_{team.pk}_id_{sid}"
                    cache.set(cache_key, True, timeout=ttl_seconds)

        return results

    @staticmethod
    def _check_exists(session_id: str, team: Team) -> bool:
        date_from = uuidv7_session_lower_bound(session_id)
        if SessionReplayEvents._check_exists_from(session_id, team, date_from):
            return True
        # The bound is a perf optimization, not a correctness gate: a clock
        # skewed past the slack would make a real recording un-findable, so
        # fall back to the unbounded scan before reporting not-found.
        return date_from is not None and SessionReplayEvents._check_exists_from(session_id, team, None)

    @staticmethod
    def _check_exists_from(session_id: str, team: Team, date_from: Optional[datetime]) -> bool:
        optional_lower_bound_clause = "AND min_first_timestamp >= %(date_from)s" if date_from else ""
        query = f"""
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
                {optional_lower_bound_clause}
            GROUP BY
                session_id
            HAVING
                expiry_time >= %(python_now)s
                AND max(is_deleted) = 0
            """
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        result = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "date_from": date_from,
                "python_now": datetime.now(pytz.timezone("UTC")),
            },
        )
        return bool(result and result[0][0] > 0)

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
        replay_session_ids = [session_id for session_id, _, _, _ in found_sessions]
        min_timestamp = min(ts for _, ts, _, _ in found_sessions)
        max_timestamp = max(ts for _, _, ts, _ in found_sessions)
        # Check which sessions also have events in the events table
        sessions_with_events = self._find_sessions_in_events(replay_session_ids, min_timestamp, max_timestamp, team)
        if not sessions_with_events:
            return set(), None, None
        # Filter to only sessions that exist in both tables
        session_ids_found = {session_id for session_id, _, _, _ in found_sessions if session_id in sessions_with_events}
        if not session_ids_found:
            return set(), None, None
        # Recalculate timestamps for filtered sessions only
        min_timestamp = min(ts for session_id, ts, _, _ in found_sessions if session_id in session_ids_found)
        max_timestamp = max(ts for session_id, _, ts, _ in found_sessions if session_id in session_ids_found)
        return session_ids_found, min_timestamp, max_timestamp

    @staticmethod
    def _find_with_timestamps(session_ids: list[str], team: Team) -> list[tuple[str, datetime, datetime, datetime]]:
        """
        Check which session IDs exist in session_replay_events within retention period.
        Returns a list of tuples of (session_id, min_timestamp, max_timestamp, expiry_time).
        Timestamps are per session, not for the entire list of sessions.
        """
        now = datetime.now(pytz.timezone("UTC"))
        # Only bound the scan when every id parses — a single unparseable id must
        # still be findable anywhere in the retained range.
        lower_bounds = [uuidv7_session_lower_bound(session_id, now) for session_id in session_ids]
        parsed_bounds = [bound for bound in lower_bounds if bound is not None]
        date_from = min(parsed_bounds) if parsed_bounds and len(parsed_bounds) == len(lower_bounds) else None

        sessions_found = SessionReplayEvents._find_with_timestamps_from(session_ids, team, now, date_from)
        if date_from is not None:
            # The bound is a perf optimization, not a correctness gate: ids the
            # bounded scan missed (clock skewed past the slack) get one unbounded
            # retry before being reported as not-found.
            found_ids = {session_id for session_id, _, _, _ in sessions_found}
            missing = [session_id for session_id in session_ids if session_id not in found_ids]
            if missing:
                sessions_found += SessionReplayEvents._find_with_timestamps_from(missing, team, now, None)
        return sessions_found

    @staticmethod
    def _find_with_timestamps_from(
        session_ids: list[str], team: Team, now: datetime, date_from: Optional[datetime]
    ) -> list[tuple[str, datetime, datetime, datetime]]:
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        optional_lower_bound_clause = "AND min_first_timestamp >= {date_from}" if date_from else ""
        query = HogQLQuery(
            query=f"""
                SELECT
                    session_id,
                    min(min_first_timestamp) as min_timestamp,
                    max(max_last_timestamp) as max_timestamp,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('day', min_timestamp) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
                FROM
                    raw_session_replay_events
                WHERE
                    session_id IN {{session_ids}}
                    AND min_first_timestamp <= {{now}}
                    {optional_lower_bound_clause}
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= {{now}}
                    AND max(is_deleted) = 0
            """,
            values={
                "session_ids": session_ids,
                "now": now,
                "date_from": date_from,
            },
        )
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        result = HogQLQueryRunner(team=team, query=query).calculate()
        if not result.results:
            return []
        sessions_found: list[tuple[str, datetime, datetime, datetime]] = [
            (row[0], row[1], row[2], row[4]) for row in result.results
        ]
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
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        result = HogQLQueryRunner(team=team, query=query).calculate()
        if not result.results:
            return set()
        return {row[0] for row in result.results}

    @staticmethod
    def get_metadata_query(
        recording_start_time: Optional[datetime] = None,
        format: Optional[str] = None,
    ) -> str:
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
                AND max(is_deleted) = 0
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
        if recording_start_time is not None:
            return self._get_metadata_from(session_id, team, recording_start_time)

        # Most callers don't know the recording's start time (it is only persisted
        # for pinned recordings); derive a lower bound from the session id instead.
        # Unlike a real start time it carries clock-skew slack, so on a miss fall
        # back to the unbounded scan rather than reporting not-found.
        derived_lower_bound = uuidv7_session_lower_bound(session_id)
        metadata = self._get_metadata_from(session_id, team, derived_lower_bound)
        if metadata is None and derived_lower_bound is not None:
            metadata = self._get_metadata_from(session_id, team, None)
        return metadata

    def _get_metadata_from(
        self,
        session_id: str,
        team: Team,
        lower_bound: Optional[datetime],
    ) -> Optional[RecordingMetadata]:
        query = self.get_metadata_query(lower_bound)
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": lower_bound,
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
                AND max(is_deleted) = 0
        """
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
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

    def get_events_query(
        self,
        session_id: str,
        metadata: RecordingMetadata,
        # Optional, to avoid modifying the existing behavior
        events_to_ignore: list[str] | None = None,
        extra_fields: list[str] | None = None,
        limit: int | None = None,
        page: int = 0,
        offset: int | None = None,
    ) -> HogQLQuery:
        """
        Helper function to build a HogQLQuery for session events, to be able to use
        both in production and locally (for example, when testing session summary).
        `offset`, when set, overrides the default `page * limit`; useful for fetching
        `limit+1` rows without inflating the offset.
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
        effective_offset = offset if offset is not None else (page * limit if limit is not None and limit > 0 else 0)
        # Pagination to allow consuming more than default 100 rows per call
        if limit is not None and limit > 0:
            q += " LIMIT {limit}"
            # Offset makes sense only if limit is defined,
            # to avoid mixing default HogQL limit and the expected one
            if effective_offset > 0:
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
                "offset": effective_offset,
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
    ) -> tuple[list | None, list | None, bool]:
        """Return `(columns, rows, has_more)`. When `limit` is set, fetches one extra row internally to detect whether more pages exist."""
        from posthog.schema import HogQLQueryResponse

        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        if limit is not None and limit > 0:
            # Fetch `limit+1` so a returned-row count of `limit+1` proves another page exists.
            # `offset` is computed from the user-facing `limit`, not the inflated fetch limit.
            hq = self.get_events_query(
                session_id, metadata, events_to_ignore, extra_fields, limit=limit + 1, offset=page * limit
            )
        else:
            hq = self.get_events_query(session_id, metadata, events_to_ignore, extra_fields, limit, page)
        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
        result: HogQLQueryResponse = HogQLQueryRunner(
            team=team,
            query=hq,
        ).calculate()
        columns, rows = result.columns, result.results
        if limit is not None and limit > 0 and rows is not None and len(rows) > limit:
            return columns, rows[:limit], True
        return columns, rows, False

    @staticmethod
    def get_sessions_from_distinct_id_query(
        format: Optional[str] = None,
        paginated: bool = False,
    ):
        """
        Helper function to build a query for listing all session IDs for a given set of distinct IDs.
        When paginated=True, adds keyset pagination (cursor, page_size parameters required).
        """
        cursor_clause = "AND session_id > %(cursor)s" if paginated else ""
        pagination_clause = "ORDER BY session_id ASC LIMIT %(page_size)s" if paginated else ""
        query = f"""
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
                    {cursor_clause}
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= %(python_now)s
                    AND max(is_deleted) = 0
                    AND anyIf(distinct_id, notEmpty(distinct_id)) IN (%(distinct_ids)s)
                {pagination_clause}
                {{optional_format_clause}}
                """
        query = query.format(
            optional_format_clause=(f"FORMAT {format}" if format else ""),
        )
        return query

    @staticmethod
    def get_sessions_from_team_id_query(
        format: Optional[str] = None,
        paginated: bool = False,
    ):
        """
        Helper function to build a query for listing all session IDs for a given team ID.
        When paginated=True, adds keyset pagination (cursor, page_size parameters required).
        """
        cursor_clause = "AND session_id > %(cursor)s" if paginated else ""
        pagination_clause = "ORDER BY session_id ASC LIMIT %(page_size)s" if paginated else ""
        query = f"""
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
                    {cursor_clause}
                GROUP BY
                    session_id
                HAVING
                    expiry_time >= %(python_now)s
                    AND max(is_deleted) = 0
                {pagination_clause}
                {{optional_format_clause}}
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
    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team_id)
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
