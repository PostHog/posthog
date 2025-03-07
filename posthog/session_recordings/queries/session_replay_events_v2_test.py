from datetime import datetime
from typing import Optional

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.session_recordings.models.metadata import RecordingMetadataV2Test


class SessionReplayEventsV2Test:
    def get_metadata(
        self,
        session_id: str,
        team: Team,
        recording_start_time: Optional[datetime] = None,
    ) -> Optional[RecordingMetadataV2Test]:
        query = """
            SELECT
                any(distinct_id),
                min(min_first_timestamp) as start_time,
                max(max_last_timestamp) as end_time,
                groupArrayArray(block_first_timestamps) as block_first_timestamps,
                groupArrayArray(block_last_timestamps) as block_last_timestamps,
                groupArrayArray(block_urls) as block_urls
            FROM
                session_replay_events_v2_test
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
            raise ValueError(f"Multiple sessions found for session_id: {session_id}")

        replay = replay_response[0]
        return RecordingMetadataV2Test(
            distinct_id=replay[0],
            start_time=replay[1],
            end_time=replay[2],
            block_first_timestamps=replay[3],
            block_last_timestamps=replay[4],
            block_urls=replay[5],
        )
