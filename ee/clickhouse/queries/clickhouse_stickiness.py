import copy
from typing import Any, Dict, List, Optional

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery, determine_compared_filter
from posthog.utils import relative_date_parse

STICKINESS_SQL = """
    SELECT countDistinct(person_id), day_count FROM (
         SELECT person_distinct_id.person_id, countDistinct(toDate(timestamp)) as day_count
         FROM events
         LEFT JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
         WHERE team_id = {team_id} AND event = '{event}' {filters} {parsed_date_from} {parsed_date_to}
         GROUP BY person_distinct_id.person_id
    ) GROUP BY day_count ORDER BY day_count
"""

STICKINESS_ACTIONS_SQL = """
    SELECT countDistinct(person_id), day_count FROM (
         SELECT person_distinct_id.person_id, countDistinct(toDate(timestamp)) as day_count
         FROM events
         LEFT JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
         WHERE team_id = {team_id} AND uuid IN ({actions_query}) {filters} {parsed_date_from} {parsed_date_to}
         GROUP BY person_distinct_id.person_id
    ) GROUP BY day_count ORDER BY day_count
"""

STICKINESS_PEOPLE_SQL = """
SELECT DISTINCT pid FROM (
    SELECT DISTINCT person_distinct_id.person_id as pid, countDistinct(toDate(timestamp)) as day_count
    FROM events
    LEFT JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id
) WHERE day_count = %(stickiness_day)s
"""


class ClickhouseStickiness(BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }

        result = self._format_stickiness_query(entity, filter, team)

        if result:
            new_dict = copy.deepcopy(serialized)
            new_dict.update(result)
            return [new_dict]

        return [serialized]

    def _format_stickiness_query(self, entity: Entity, filter: Filter, team: Team) -> Optional[Dict[str, Any]]:
        if not filter.date_to or not filter.date_from:
            raise ValueError("_stickiness needs date_to and date_from set")
        range_days = (filter.date_to - filter.date_from).days + 2

        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)

        params: Dict = {"team_id": team.pk}
        params = {**params, **prop_filter_params}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)
            if action_query == "":
                return None

            params = {**params, **action_params}
            content_sql = STICKINESS_ACTIONS_SQL.format(
                team_id=team.pk,
                actions_query=action_query,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="AND uuid IN {filters}".format(filters=prop_filters) if filter.properties else "",
            )
        else:
            content_sql = STICKINESS_SQL.format(
                team_id=team.pk,
                event=entity.id,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="AND uuid IN {filters}".format(filters=prop_filters) if filter.properties else "",
            )

        aggregated_counts = sync_execute(content_sql, params)

        response: Dict[int, int] = {}
        for result in aggregated_counts:
            response[result[1]] = result[0]

        labels = []
        data = []

        for day in range(1, range_days):
            label = "{} day{}".format(day, "s" if day > 1 else "")
            labels.append(label)
            data.append(response[day] if day in response else 0)

        return {
            "labels": labels,
            "days": [day for day in range(1, range_days)],
            "data": data,
            "count": sum(data),
        }

    def _calculate_stickiness(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        if not filter._date_from:
            filter._date_from = relative_date_parse("-7d")
        if not filter._date_to:
            filter._date_to = timezone.now()

        result = []

        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                entity.name = Action.objects.only("name").get(team=team, pk=entity.id).name
            entity_result = self._serialize_entity(entity, filter, team)
            result.extend(entity_result)

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self._calculate_stickiness(filter, team)
