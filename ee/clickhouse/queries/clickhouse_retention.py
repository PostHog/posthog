from typing import Any, Dict, List

from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery

RETENTION_SQL = """
select first_event, delta as days_on_site, groupArray(person_id) from 
(
    select pdi.person_id
    , toDate(min(e.timestamp)) first_event
    , max(e.timestamp) last_event
    , datediff('day', min(e.timestamp), max(e.timestamp)) delta
    from events e join person_distinct_id pdi on e.distinct_id = pdi.distinct_id
    where e.timestamp >= toDate({date})
    AND e.team_id = {team_id}
    group by pdi.person_id
    having toDate(min(e.timestamp)) = toDate({date})
)
group by first_event, delta
order by first_event, delta asc
limit {days};
"""


class ClickhouseRetention(BaseQuery):
    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return []
