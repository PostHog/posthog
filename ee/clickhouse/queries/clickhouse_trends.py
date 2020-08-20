from typing import Any, Dict, List

from ee.clickhouse.client import ch_client
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery

TEST_SQL = """
SELECT count(*) as total, toDateTime(toStartOfDay(timestamp), 'UTC') as day_start from clickhouseevent where team_id = 1 and event = '$pageview' and timestamp > '2020-08-06 00:00:00' and timestamp < '2020-08-20 00:00:00' GROUP BY toStartOfDay(timestamp)
"""

NULL_SQL = """
SELECT toUInt16(0) AS total, toStartOfDay(now() - number * 3600 * 24) as day_start from numbers(14)
"""


class ClickhouseTrends(BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: Filter, team: Team) -> Dict[str, Any]:
        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }
        result = ch_client.execute(
            "SELECT SUM(total), day_start from ({null_sql} UNION ALL {content_sql}) group by day_start order by day_start".format(
                null_sql=NULL_SQL, content_sql=TEST_SQL
            )
        )
        counts = [item[0] for item in result]
        dates = [item[1].strftime("%Y-%m-%d") for item in result]
        labels = [item[1].strftime("%a. %-d %B") for item in result]
        serialized.update(data=counts, labels=labels, days=dates, count=sum(counts))
        return serialized

    def _calculate_trends(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        result = []
        for entity in filter.entities:
            entity_result = self._serialize_entity(entity, filter, team)
            result.append(entity_result)

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self._calculate_trends(filter, team)


def get_interval_annotation(key: str) -> str:
    map: Dict[str, Any] = {
        "minute": "toStartOfMinute(timestamp)",
        "hour": "toStartOfHour(timestamp)",
        "day": "toStartOfDay(timestamp)",
        "week": "toStartOfWeek(timestamp)",
        "month": "toStartOfMonth(timestamp)",
    }
    notation = map.get(key)
    if notation is None:
        return "toStartOfDay(timestamp)"  # default

    return notation
