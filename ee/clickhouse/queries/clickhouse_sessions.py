from typing import Any, Dict, List

from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery

SESSION_SQL = """
SELECT 
    distinct_id, 
    gid, 
    groupArray(event) events, 
    groupArray(timestamp) timestamps, 
    dateDiff('second', arrayReduce('min', 
    groupArray(timestamp)), 
    arrayReduce('max', groupArray(timestamp))) AS elapsed 
FROM 
(
    SELECT
    distinct_id, 
    event,
    timestamp,
    arraySum(arraySlice(gids, 1, idx)) AS gid
    FROM
    (
    SELECT groupArray(timestamp) as timestamps, groupArray(event) as events, groupArray(distinct_id) as distinct_ids, groupArray(new_session) AS gids
        FROM
        (
            SELECT 
            distinct_id, 
            event,
            timestamp, 
            neighbor(distinct_id, -1) as possible_neighbor,
            neighbor(event, -1) as possible_prev_event, 
            neighbor(timestamp, -1) as possible_prev, 
            if(possible_neighbor != distinct_id or dateDiff('minute', possible_prev, timestamp) > 30, 1, 0) as new_session
            FROM (
                SELECT 
                    timestamp, 
                    distinct_id, 
                    event 
                FROM events 
                WHERE team_id = {team_id} and timestamp >= toDate('{date_from}') and timestamp <= toDate('{date_to}') 
                GROUP BY distinct_id, timestamp, event ORDER BY timestamp DESC
            )
        )
    )
    ARRAY JOIN
    distinct_ids as distinct_id,
    events as event,
    timestamps as timestamp,
    arrayEnumerate(gids) AS idx 
) 
GROUP BY 
distinct_id, 
gid 
"""

AVERAGE_SQL = """
    SELECT AVG(elapsed) as avg FROM 
    ({sessions})
""".format(
    sessions=SESSION_SQL
)

DIST_SQL = """
    SELECT 
        countIf(elapsed = 0)  as first,
        countIf(elapsed > 0 and elapsed <= 3)  as second,
        countIf(elapsed > 3 and elapsed <= 10)  as third,
        countIf(elapsed > 10 and elapsed <= 30)  as fourth,
        countIf(elapsed > 30 and elapsed <= 60)  as fifth,
        countIf(elapsed > 60 and elapsed <= 180)  as sixth,
        countIf(elapsed > 180 and elapsed <= 600)  as sevent,
        countIf(elapsed > 600 and elapsed <= 1800)  as eighth,
        countIf(elapsed > 1800 and elapsed <= 3600)  as ninth,
        countIf(elapsed > 3600)  as tength
    FROM 
    ({sessions})
""".format(
    sessions=SESSION_SQL
)


class ClickhouseSessions(BaseQuery):
    def calculate_list(self):
        pass

    def calculate_avg(self):
        pass

    def calculate_dist(self):
        pass

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return []
