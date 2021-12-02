import copy
import urllib.parse
from typing import Any, Dict, List, Union

from django.db import connection
from django.db.models import Count
from django.db.models.query import Prefetch, QuerySet
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models import Action, Entity, Team
from posthog.models.action_step import ActionStep
from posthog.models.event import Event, EventManager
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.person import Person
from posthog.queries import base

from .base import BaseQuery, filter_events, filter_persons, handle_compare, process_entity_for_events


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
            .filter(interval_count__lte=filter.total_intervals)
        )

        events_sql, events_sql_params = events.query.sql_with_params()
        aggregated_query = "select count(v.person_id), v.interval_count from ({}) as v group by v.interval_count".format(
            events_sql
        )
        counts = execute_custom_sql(aggregated_query, events_sql_params)
        return self.process_result(counts, filter, entity)

    def process_result(self, counts: List, filter: StickinessFilter, entity: Entity) -> Dict[str, Any]:

        response: Dict[int, int] = {}
        for result in counts:
            response[result[1]] = result[0]

        labels = []
        data = []
        for day in range(1, filter.total_intervals):
            label = "{} {}{}".format(day, filter.interval, "s" if day > 1 else "")
            labels.append(label)
            data.append(response[day] if day in response else 0)
        filter_params = filter.to_params()

        return {
            "labels": labels,
            "days": [day for day in range(1, filter.total_intervals)],
            "data": data,
            "count": sum(data),
            "filter": filter_params,
            "persons_urls": self._get_persons_url(filter, entity),
        }

    def _get_persons_url(self, filter: StickinessFilter, entity: Entity) -> List[Dict[str, Any]]:
        persons_url = []
        for interval_idx in range(1, filter.total_intervals):
            filter_params = filter.to_params()
            extra_params = {
                "stickiness_days": interval_idx,
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
            }
            parsed_params: Dict[str, Union[Any, int, str]] = {**filter_params, **extra_params}
            persons_url.append(
                {"filter": extra_params, "url": f"api/person/stickiness/?{urllib.parse.urlencode(parsed_params)}",}
            )
        return persons_url

    def run(self, filter: StickinessFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:

        response = []
        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                entity.name = Action.objects.only("name").get(team=team, pk=entity.id).name

            entity_resp = handle_compare(filter=filter, func=self._serialize_entity, team=team, entity=entity)
            response.extend(entity_resp)
        return response

    def people(self, target_entity: Entity, filter: StickinessFilter, team: Team, request, *args, **kwargs):
        results = self._retrieve_people(target_entity, filter, team, request)
        return results

    def _retrieve_people(self, target_entity: Entity, filter: StickinessFilter, team: Team, request: Request):
        from posthog.api.person import PersonSerializer

        events = stickiness_process_entity_type(target_entity, team, filter)
        events = stickiness_format_intervals(events, filter)
        people = stickiness_fetch_people(events, team, filter)
        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        people = filter_persons(team.id, request, people)

        return PersonSerializer(people, many=True).data


def stickiness_process_entity_type(target_entity: Entity, team: Team, filter: StickinessFilter) -> QuerySet:

    events: Union[EventManager, QuerySet] = Event.objects.none()
    if target_entity.type == TREND_FILTER_TYPE_EVENTS:
        events = base.process_entity_for_events(target_entity, team_id=team.pk, order_by=None).filter(
            base.filter_events(team.pk, filter, target_entity)
        )
    elif target_entity.type == TREND_FILTER_TYPE_ACTIONS:
        actions = Action.objects.filter(deleted=False, team=team)
        actions = actions.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
        try:
            actions.get(pk=target_entity.id)
        except Action.DoesNotExist:
            return Event.objects.none()

        events = base.process_entity_for_events(target_entity, team_id=team.pk, order_by=None).filter(
            base.filter_events(team.pk, filter, target_entity)
        )
    else:
        raise ValidationError("Target entity must be action or event.")
    return events


def stickiness_format_intervals(events: QuerySet, filter: StickinessFilter) -> QuerySet:
    return (
        events.values("person_id")
        .annotate(day_count=Count(filter.trunc_func("timestamp"), distinct=True))
        .filter(day_count=filter.selected_interval)
    )


def stickiness_fetch_people(events: QuerySet, team: Team, filter: StickinessFilter, use_offset=True) -> QuerySet:
    return Person.objects.filter(
        team=team,
        id__in=[p["person_id"] for p in (events[filter.offset : filter.offset + 100] if use_offset else events)],
    )
