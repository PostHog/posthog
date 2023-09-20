from datetime import datetime
from typing import Optional, Tuple, List

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.session_recordings.models.metadata import (
    RecordingMetadata,
)


class SessionReplayEvents:
    def get_metadata(
        self, session_id: str, team: Team, recording_start_time: Optional[datetime] = None
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
            {"team_id": team.pk, "session_id": session_id, "recording_start_time": recording_start_time},
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
