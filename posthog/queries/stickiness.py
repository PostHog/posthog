from typing import List, Dict, Any
from .base import filter_events, handle_compare, process_entity_for_events
from posthog.models import Entity, Filter, Team, Event
from django.db.models import QuerySet, Count, functions
from django.utils.timezone import now
from django.db import connection
import copy


def execute_custom_sql(query, params):
    cursor = connection.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


class Stickiness:
    def _serialize_entity(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:
        if filter.interval is None:
            filter.interval = "day"

        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }
        response = []
        events = process_entity_for_events(entity=entity, team_id=team_id, order_by=None,)
        events = events.filter(filter_events(team_id, filter, entity))
        new_dict = copy.deepcopy(serialized)
        new_dict.update(self.stickiness(filtered_events=events, entity=entity, filter=filter, team_id=team_id))
        response.append(new_dict)
        return response

    def stickiness(self, filtered_events: QuerySet, entity: Entity, filter: Filter, team_id: int) -> Dict[str, Any]:
        if not filter.date_to or not filter.date_from:
            raise ValueError("_stickiness needs date_to and date_from set")
        range_days = (filter.date_to - filter.date_from).days + 2

        events = (
            filtered_events.filter(filter_events(team_id, filter, entity))
            .values("person_id")
            .annotate(day_count=Count(functions.TruncDay("timestamp"), distinct=True))
            .filter(day_count__lte=range_days)
        )

        events_sql, events_sql_params = events.query.sql_with_params()
        aggregated_query = "select count(v.person_id), v.day_count from ({}) as v group by v.day_count".format(
            events_sql
        )
        aggregated_counts = execute_custom_sql(aggregated_query, events_sql_params)

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

    def run(self, filter: Filter, team: Team) -> Dict[str, Any]:
        response = []

        if not filter.date_from:
            filter._date_from = (
                Event.objects.filter(team_id=team.pk)
                .order_by("timestamp")[0]
                .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
        if not filter.date_to:
            filter._date_to = now().isoformat()

        for entity in filter.entities:

            entity_resp = handle_compare(entity=entity, filter=filter, func=self._serialize_entity, team_id=team.pk)
            response.extend(entity_resp)
        return response
