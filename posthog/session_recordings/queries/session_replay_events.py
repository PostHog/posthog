from datetime import datetime, timedelta
from typing import Optional

import pytz
from django.conf import settings
from django.core.cache import cache

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature

from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from posthog.session_recordings.models.metadata import (
    RecordingMetadata,
)


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

    def get_metadata(
        self,
        session_id: str,
        team: Team,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingMetadata]:
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
                argMinMerge(snapshot_source) as snapshot_source
            FROM
                session_replay_events
            PREWHERE
                team_id = %(team_id)s
                AND session_id = %(session_id)s
                {optional_timestamp_clause}
            GROUP BY
                session_id
        """
        query = query.format(
            optional_timestamp_clause=(
                "AND min_first_timestamp >= %(recording_start_time)s" if recording_start_time else ""
            )
        )

        replay_response: list[tuple] = sync_execute(
            query,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_start_time": recording_start_time,
            },
        )

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
        )

    def get_events(
        self,
        session_id: str,
        team: Team,
        metadata: RecordingMetadata,
        events_to_ignore: list[str] | None,
        extra_fields: list[str] | None = None,
    ) -> tuple[list | None, list | None]:
        from posthog.schema import HogQLQuery, HogQLQueryResponse
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        fields = [
            "event",
            "timestamp",
            "elements_chain_href",
            "elements_chain_texts",
            "elements_chain_elements",
            "properties.$window_id",
            "properties.$current_url",
            "properties.$event_type",
        ]
        if extra_fields:
            fields.extend(extra_fields)

        # TODO: Find a better way to inject the fields (providing string or list of strings to hq `values` just returns the string back)
        q = f"select {', '.join(fields)} from events"
        q += """
            where timestamp >= {start_time} and timestamp <= {end_time}
            and $session_id = {session_id}
            """
        if events_to_ignore:
            q += " and event not in {events_to_ignore}"

        q += " order by timestamp asc"

        hq = HogQLQuery(
            query=q,
            values={
                # add some wiggle room to the timings, to ensure we get all the events
                # the time range is only to stop CH loading too much data to find the session
                "start_time": metadata["start_time"] - timedelta(seconds=100),
                "end_time": metadata["end_time"] + timedelta(seconds=100),
                "session_id": session_id,
                "events_to_ignore": events_to_ignore,
            },
        )

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

        # NOTE: The date we started reliably ingested data to blob storage
        days_since_blob_ingestion = (datetime.now() - datetime(2023, 8, 1)).days

        if days_since_blob_ingestion < ttl_days:
            ttl_days = days_since_blob_ingestion
    else:
        ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7
    return ttl_days
