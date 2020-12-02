import copy
from typing import Any, Dict, List

from django.db import connection
from django.db.models import Count, functions
from django.utils import timezone

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Entity, Event, Filter, Team
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.utils import relative_date_parse

from .base import BaseQuery, filter_events, handle_compare, process_entity_for_events


def execute_custom_sql(query, params):
    cursor = connection.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


class Stickiness(BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: StickinessFilter, team_id: int) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }
        response = []
        new_dict = copy.deepcopy(serialized)
        new_dict.update(self.stickiness(entity=entity, filter=filter, team_id=team_id))
        response.append(new_dict)
        return response

    def stickiness(self, entity: Entity, filter: StickinessFilter, team_id: int) -> Dict[str, Any]:

        events = process_entity_for_events(entity=entity, team_id=team_id, order_by=None,)
        events = events.filter(filter_events(team_id, filter, entity))

        events = (
            events.filter(filter_events(team_id, filter, entity))
            .values("person_id")
            .annotate(interval_count=Count(filter.trunc_func("timestamp"), distinct=True))
            .filter(interval_count__lte=filter.num_intervals)
        )

        events_sql, events_sql_params = events.query.sql_with_params()
        aggregated_query = "select count(v.person_id), v.interval_count from ({}) as v group by v.interval_count".format(
            events_sql
        )
        counts = execute_custom_sql(aggregated_query, events_sql_params)
        return self.process_result(counts, filter)

    def process_result(self, counts: List, filter: StickinessFilter) -> Dict[str, Any]:

        response: Dict[int, int] = {}
        for result in counts:
            response[result[1]] = result[0]

        labels = []
        data = []
        for day in range(1, filter.num_intervals):
            label = "{} {}{}".format(day, filter.interval, "s" if day > 1 else "")
            labels.append(label)
            data.append(response[day] if day in response else 0)

        return {
            "labels": labels,
            "days": [day for day in range(1, filter.num_intervals)],
            "data": data,
            "count": sum(data),
        }

    def run(self, filter: StickinessFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:

        response = []

        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                entity.name = Action.objects.only("name").get(team=team, pk=entity.id).name

            entity_resp = handle_compare(filter=filter, func=self._serialize_entity, team=team, entity=entity)
            response.extend(entity_resp)
        return response
