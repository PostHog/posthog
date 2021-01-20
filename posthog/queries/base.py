import copy
from typing import Any, Callable, Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Exists, OuterRef, Q, QuerySet

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.entity import Entity
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.utils import get_compare_period_dates

"""
process_entity_for_events takes in an Entity and team_id, and returns an Event QuerySet that's correctly filtered
"""


def process_entity_for_events(entity: Entity, team_id: int, order_by="-id") -> QuerySet:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        events = Event.objects.filter(action__pk=entity.id).add_person_id(team_id)
        if order_by:
            events = events.order_by(order_by)
        return events
    elif entity.type == TREND_FILTER_TYPE_EVENTS:
        return Event.objects.filter_by_event_with_people(event=entity.id, team_id=team_id, order_by=order_by)
    return QuerySet()


def determine_compared_filter(filter):
    if not filter.date_to or not filter.date_from:
        raise ValueError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(filter.date_from, filter.date_to)
    compared_filter = Filter(
        data={**filter._data, "date_from": date_from.date().isoformat(), "date_to": date_to.date().isoformat()}
    )
    return compared_filter


def convert_to_comparison(trend_entity: List[Dict[str, Any]], filter, label: str) -> List[Dict[str, Any]]:
    for entity in trend_entity:
        days = [i for i in range(len(entity["days"]))]
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {
                "labels": labels,
                "days": days,
                "label": "{} - {}".format(entity["label"], label),
                "chartLabel": "{} - {}".format(entity["label"], label),
                "dates": entity["days"],
                "compare": True,
            }
        )
    return trend_entity


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(filter, func: Callable, team: Team, **kwargs) -> List:
    entities_list = []
    trend_entity = func(filter=filter, team_id=team.pk, **kwargs)
    if filter.compare:
        trend_entity = convert_to_comparison(trend_entity, filter, "current")
        entities_list.extend(trend_entity)

        compared_filter = determine_compared_filter(filter)
        compared_trend_entity = func(filter=compared_filter, team_id=team.pk, **kwargs)

        compared_trend_entity = convert_to_comparison(compared_trend_entity, compared_filter, "previous",)
        entities_list.extend(compared_trend_entity)
    else:
        entities_list.extend(trend_entity)
    return entities_list


TIME_IN_SECONDS: Dict[str, Any] = {
    "minute": 60,
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,
}

"""
filter_events takes team_id, filter, entity and generates a Q objects that you can use to filter a QuerySet
"""


def filter_events(
    team_id: int, filter, entity: Optional[Entity] = None, include_dates: bool = True, interval_annotation=None
) -> Q:
    filters = Q()
    if filter.date_from and include_dates:
        filters &= Q(timestamp__gte=filter.date_from)
    relativity = relativedelta(days=1)
    if filter.interval == "hour":
        relativity = relativedelta(hours=1)
    elif filter.interval == "minute":
        relativity = relativedelta(minutes=1)
    elif filter.interval == "week":
        relativity = relativedelta(weeks=1)
    elif filter.interval == "month":
        relativity = relativedelta(months=1) - relativity  # go to last day of month instead of first of next
    if include_dates:
        filters &= Q(timestamp__lte=filter.date_to + relativity)
    if filter.properties:
        filters &= properties_to_Q(filter.properties, team_id=team_id)
    if entity and entity.properties:
        filters &= properties_to_Q(entity.properties, team_id=team_id)
    return filters


def properties_to_Q(properties: List[Property], team_id: int, is_person_query: bool = False) -> Q:
    """
    Converts a filter to Q, for use in Django ORM .filter()
    If you're filtering a Person QuerySet, use is_person_query to avoid doing an unnecessary nested loop
    """
    filters = Q()

    if len(properties) == 0:
        return filters

    if is_person_query:
        for property in properties:
            filters &= property.property_to_Q()
        return filters

    person_properties = [prop for prop in properties if prop.type == "person"]
    if len(person_properties) > 0:
        person_Q = Q()
        for property in person_properties:
            person_Q &= property.property_to_Q()
        filters &= Q(Exists(Person.objects.filter(person_Q, id=OuterRef("person_id"),).only("pk")))

    for property in [prop for prop in properties if prop.type == "event"]:
        filters &= property.property_to_Q()

    # importing from .event and .cohort below to avoid importing from partially initialized modules

    element_properties = [prop for prop in properties if prop.type == "element"]
    if len(element_properties) > 0:
        from posthog.models.event import Event

        filters &= Q(
            Exists(
                Event.objects.filter(pk=OuterRef("id"))
                .filter(
                    **Event.objects.filter_by_element(
                        {item.key: item.value for item in element_properties}, team_id=team_id,
                    )
                )
                .only("id")
            )
        )

    cohort_properties = [prop for prop in properties if prop.type == "cohort"]
    if len(cohort_properties) > 0:
        from posthog.models.cohort import CohortPeople

        for item in cohort_properties:
            if item.key == "id":
                filters &= Q(
                    Exists(
                        CohortPeople.objects.filter(cohort_id=int(item.value), person_id=OuterRef("person_id"),).only(
                            "id"
                        )
                    )
                )
    return filters


def entity_to_Q(entity: Entity, team_id: int) -> Q:
    result = Q(action__pk=entity.id) if entity.type == TREND_FILTER_TYPE_ACTIONS else Q(event=entity.id)
    if entity.properties:
        result &= properties_to_Q(entity.properties, team_id)
    return result


class BaseQuery:
    """
        Run needs to be implemented in the individual Query class. It takes in a Filter, Team
        and optionally other arguments within kwargs (though use sparingly!)

        The output is a List comprised of Dicts. What those dicts looks like depend on the needs of the frontend.
    """

    def run(self, filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        raise NotImplementedError("You need to implement run")
