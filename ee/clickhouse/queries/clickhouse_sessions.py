from datetime import datetime
from typing import Any, Dict, List, Tuple

from django.db.models import query

from ee.clickhouse.client import ch_client
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
            if(possible_neighbor != distinct_id or dateDiff('minute', timestamp, possible_prev) > 30, 1, 0) as new_session
            FROM (
                SELECT 
                    timestamp, 
                    distinct_id, 
                    event 
                FROM events 
                WHERE team_id = {team_id} and timestamp >= parseDateTimeBestEffort('{date_from}') and timestamp <= parseDateTimeBestEffort('{date_to}') 
                GROUP BY distinct_id, timestamp, event ORDER BY distinct_id, timestamp DESC
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

# TODO: handle date and defaults
class ClickhouseSessions(BaseQuery):

    # TODO: handle offset
    def calculate_list(self, filter: Filter, team: Team, offset: int):
        query_result = ch_client.execute(
            SESSION_SQL.format(team_id=team.pk, date_from=filter.date_from, date_to=filter.date_to or datetime.now())
        )
        result = self._parse_list_results(query_result)
        return result

    def _parse_list_results(self, results: List[Tuple]):
        final = []
        for result in results:
            final.append(
                {
                    "distinct_id": result[0],
                    "global_session_id": result[1],
                    "events": result[2],
                    "timestamps": result[3],
                    "length": result[4],
                }
            )
        return final

    def calculate_avg(self, filter: Filter, team: Team):
        result = ch_client.execute(
            AVERAGE_SQL.format(team_id=team.pk, date_from=filter.date_from, date_to=filter.date_to or datetime.now())
        )
        return result

    def calculate_dist(self, filter: Filter, team: Team):
        result = ch_client.execute(DIST_SQL.format(team_id=team.pk, date_from=filter.date_from, date_to=filter.date_to))
        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:

        session_type = kwargs.get("session_type", None)
        offset = kwargs.get("offset", 0)

        result: List = []
        if session_type == "avg":
            result = self.calculate_avg(filter, team)
        elif session_type == "dist":
            result = self.calculate_dist(filter, team)
        else:
            result = self.calculate_list(filter, team, offset)

        return result
