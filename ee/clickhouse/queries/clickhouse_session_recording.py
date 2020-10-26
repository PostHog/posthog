import datetime
from typing import List

from ee.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.queries.session_recording import add_session_recording_ids as _add_session_recording_ids

add_session_recording_ids = lambda *args, **kw: add_session_recording_ids(*args, **kw, query=query_sessions_in_range)


def query_sessions_in_range(team: Team, start_time: datetime.datetime, end_time: datetime.datetime) -> List[dict]:
    query = """
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            AND timestamp >= %(start_time)s
            AND timestamp <= %(end_time)s
        GROUP BY distinct_id, session_id
    """

    return sync_execute(
        query,
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
    )
