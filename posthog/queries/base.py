import copy
from typing import Any, Callable, Dict, List, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import Q, QuerySet

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_CUMULATIVE, TRENDS_STICKINESS
from posthog.models import Entity, Event, Filter, Team
from posthog.utils import get_compare_period_dates, timezone

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


def _determine_compared_filter(filter: Filter) -> Filter:
    if not filter.date_to or not filter.date_from:
        raise ValueError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(filter.date_from, filter.date_to)
    compared_filter = copy.deepcopy(filter)
    compared_filter._date_from = date_from.date().isoformat()
    compared_filter._date_to = date_to.date().isoformat()
    return compared_filter


def _convert_to_comparison(trend_entity: List[Dict[str, Any]], filter: Filter, label: str) -> List[Dict[str, Any]]:
    for entity in trend_entity:
        days = [i for i in range(len(entity["days"]))]
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {"labels": labels, "days": days, "label": label, "dates": entity["days"], "compare": True,}
        )
    return trend_entity


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(entity: Entity, filter: Filter, func: Callable, team_id: int) -> List:
    entities_list = []
    trend_entity = func(entity=entity, filter=filter, team_id=team_id)
    if filter.compare:
        trend_entity = _convert_to_comparison(trend_entity, filter, "{} - {}".format(entity.name, "current"))
        entities_list.extend(trend_entity)

        compared_filter = _determine_compared_filter(filter)
        compared_trend_entity = func(entity=entity, filter=compared_filter, team_id=team_id)

        compared_trend_entity = _convert_to_comparison(
            compared_trend_entity, compared_filter, "{} - {}".format(entity.name, "previous"),
        )
        entities_list.extend(compared_trend_entity)
    else:
        entities_list.extend(trend_entity)
    return entities_list


"""
filter_events takes team_id, filter, entity and generates a Q objects that you can use to filter a QuerySet
"""


def filter_events(team_id: int, filter: Filter, entity: Optional[Entity] = None) -> Q:
    filters = Q()
    if filter.date_from:
        filters &= Q(timestamp__gte=filter.date_from)
    if filter.date_to:
        relativity = relativedelta(days=1)
        if filter.interval == "hour":
            relativity = relativedelta(hours=1)
        elif filter.interval == "minute":
            relativity = relativedelta(minutes=1)
        elif filter.interval == "week":
            relativity = relativedelta(weeks=1)
        elif filter.interval == "month":
            relativity = relativedelta(months=1) - relativity  # go to last day of month instead of first of next
        filters &= Q(timestamp__lte=filter.date_to + relativity)
    if filter.properties:
        filters &= filter.properties_to_Q(team_id=team_id)
    if entity and entity.properties:
        filters &= entity.properties_to_Q(team_id=team_id)
    return filters


class BaseQuery:
    """
        Run needs to be implemented in the individual Query class. It takes in a Filter, Team
        and optionally other arguments within kwargs (though use sparingly!)

        The output is a List comprised of Dicts. What those dicts looks like depend on the needs of the frontend.
    """

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        raise NotImplementedError("You need to implement run")
