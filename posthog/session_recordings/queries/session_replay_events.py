import re
from datetime import datetime
from typing import Optional, Tuple, List, Set

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature

from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from posthog.session_recordings.models.metadata import (
    RecordingMetadata,
)


def is_boring_string(element: str) -> bool:
    return element in ["a", "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6"]


def reduce_elements_chain(columns: List | None, results: List | None) -> Tuple[List | None, List | None]:
    if columns is None or results is None:
        return columns, results

    # find elements_chain column index
    elements_chain_index = None
    for i, column in enumerate(columns):
        if column == "elements_chain":
            elements_chain_index = i
            break

    reduced_results = []
    for result in results:
        if elements_chain_index is None:
            reduced_results.append(result)
            continue

        elements_chain: str | None = result[elements_chain_index]
        if not elements_chain:
            reduced_results.append(result)
            continue

        # the elements chain has lots of information that we don't need
        reduced_elements_chain: Set[str] = set()
        split_elements = re.split(r"_{2,}|[.:;,]", elements_chain)
        for element in split_elements:
            if len(element) < 3:
                continue

            if not is_boring_string(element):
                reduced_elements_chain.add(element)

        result_list = list(result)
        result_list[elements_chain_index] = ", ".join(reduced_elements_chain) if len(reduced_elements_chain) > 0 else ""
        reduced_results.append(tuple(result_list))

    return columns, reduced_results


class SessionReplayEvents:
    def exists(self, session_id: str, team: Team) -> bool:
        # TODO we could cache this result when its result is True.
        # Once we know that session exists we don't need to check again (until the end of the day since TTL might apply)
        result = sync_execute(
            """
            SELECT count(1)
            FROM session_replay_events
            WHERE team_id = %(team_id)s
            AND session_id = %(session_id)s
            -- we should check for the `ttl_days(team)` TTL here,
            -- but for a shared/pinned recording
            -- the TTL effectively becomes 1 year
            -- and we don't know which we're dealing with
            AND min_first_timestamp >= now() - INTERVAL 370 DAY
            """,
            {
                "team_id": team.pk,
                "session_id": session_id,
                "recording_ttl_days": ttl_days(team),
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
                sum(console_error_count) as console_error_count
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
            optional_timestamp_clause="AND min_first_timestamp >= %(recording_start_time)s"
            if recording_start_time
            else ""
        )

        replay_response: List[Tuple] = sync_execute(
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
        )

    def get_events(
        self, session_id: str, team: Team, metadata: RecordingMetadata, events_to_ignore: List[str] | None
    ) -> Tuple[List | None, List | None]:
        from posthog.schema import HogQLQuery, HogQLQueryResponse
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        q = """
            select event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type
            from events
            where timestamp >= {start_time} and timestamp <= {end_time}
            and $session_id = {session_id}
            """
        if events_to_ignore:
            q += " and event not in {events_to_ignore}"

        hq = HogQLQuery(
            query=q,
            values={
                "start_time": metadata["start_time"],
                "end_time": metadata["end_time"],
                "session_id": session_id,
                "events_to_ignore": events_to_ignore,
            },
        )

        result: HogQLQueryResponse = HogQLQueryRunner(
            team=team,
            query=hq,
        ).calculate()

        return reduce_elements_chain(result.columns, result.results)


def ttl_days(team: Team) -> int:
    ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7
    if is_cloud():
        # NOTE: We use Playlists as a proxy to see if they are subbed to Recordings
        is_paid = team.organization.is_feature_available(AvailableFeature.RECORDINGS_PLAYLISTS)
        ttl_days = settings.REPLAY_RETENTION_DAYS_MAX if is_paid else settings.REPLAY_RETENTION_DAYS_MIN

        # NOTE: The date we started reliably ingested data to blob storage
        days_since_blob_ingestion = (datetime.now() - datetime(2023, 8, 1)).days

        if days_since_blob_ingestion < ttl_days:
            ttl_days = days_since_blob_ingestion

    return ttl_days
