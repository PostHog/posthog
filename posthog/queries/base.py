import datetime
import re
from typing import Any, Callable, Dict, List, TypeVar, Union, cast

from dateutil import parser
from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import ValidationError

from posthog.models.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.person import Person
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.queries.util import convert_to_datetime_aware
from posthog.utils import get_compare_period_dates

F = TypeVar("F", Filter, PathFilter)


def determine_compared_filter(filter: F) -> F:
    if not filter.date_to or not filter.date_from:
        raise ValidationError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(
        filter.date_from,
        filter.date_to,
        filter.date_from_delta_mapping,
        filter.date_to_delta_mapping,
        filter.interval,
    )

    return filter.with_data({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})


def convert_to_comparison(trend_entities: List[Dict[str, Any]], filter, label: str) -> List[Dict[str, Any]]:
    for entity in trend_entities:
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {
                "labels": labels,
                "days": entity["days"],
                "label": entity["label"],
                "compare_label": label,
                "compare": True,
            }
        )
    return trend_entities


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(filter, func: Callable, team: Team, **kwargs) -> List:
    all_entities = []
    base_entitites = func(filter=filter, team=team, **kwargs)
    if filter.compare:
        base_entitites = convert_to_comparison(base_entitites, filter, "current")
        all_entities.extend(base_entitites)

        compared_filter = determine_compared_filter(filter)
        comparison_entities = func(filter=compared_filter, team=team, **kwargs)
        comparison_entities = convert_to_comparison(comparison_entities, compared_filter, "previous")
        all_entities.extend(comparison_entities)
    else:
        all_entities.extend(base_entitites)
    return all_entities


def match_property(property: Property, override_property_values: Dict[str, Any]) -> bool:
    # only looks for matches where key exists in override_property_values
    # doesn't support operator is_not_set

    if property.key not in override_property_values:
        raise ValidationError("can't match properties without an override value")

    if property.operator == "is_not_set":
        raise ValidationError("can't match properties with operator is_not_set")

    key = property.key
    operator = property.operator or "exact"
    value = property.value
    override_value = override_property_values[key]

    if operator == "exact":
        if isinstance(value, list):
            return override_value in value
        return value == override_value

    if operator == "is_not":
        if isinstance(value, list):
            return override_value not in value
        return value != override_value

    if operator == "is_set":
        return key in override_property_values

    if operator == "icontains":
        return str(value).lower() in str(override_value).lower()

    if operator == "not_icontains":
        return str(value).lower() not in str(override_value).lower()

    if operator in ("regex", "not_regex"):
        try:
            pattern = re.compile(str(value))
            match = pattern.search(str(override_value))

            if operator == "regex":
                return match is not None
            else:
                return match is None

        except re.error:
            return False

    if operator == "gt":
        return type(override_value) == type(value) and override_value > value

    if operator == "gte":
        return type(override_value) == type(value) and override_value >= value

    if operator == "lt":
        return type(override_value) == type(value) and override_value < value

    if operator == "lte":
        return type(override_value) == type(value) and override_value <= value

    if operator in ["is_date_before", "is_date_after"]:
        try:
            parsed_date = parser.parse(str(value))
            parsed_date = convert_to_datetime_aware(parsed_date)
        except Exception:
            return False

        if isinstance(override_value, datetime.datetime):
            override_date = convert_to_datetime_aware(override_value)
            if operator == "is_date_before":
                return override_date < parsed_date
            else:
                return override_date > parsed_date
        elif isinstance(override_value, datetime.date):
            if operator == "is_date_before":
                return override_value < parsed_date.date()
            else:
                return override_value > parsed_date.date()
        elif isinstance(override_value, str):
            try:
                override_date = parser.parse(override_value)
                override_date = convert_to_datetime_aware(override_date)
                if operator == "is_date_before":
                    return override_date < parsed_date
                else:
                    return override_date > parsed_date
            except Exception:
                return False

    return False


def properties_to_Q(
    properties: List[Property],
    team_id: int,
    is_direct_query: bool = False,
    override_property_values: Dict[str, Any] = {},
) -> Q:
    """
    Converts a filter to Q, for use in Django ORM .filter()
    If you're filtering a Person/Group QuerySet, use is_direct_query to avoid doing an unnecessary nested loop
    """
    filters = Q()

    if len(properties) == 0:
        return filters

    if is_direct_query:
        for property in properties:
            # short circuit query if key exists in override_property_values
            if property.key in override_property_values and property.operator != "is_not_set":
                # if match found, do nothing to Q
                # if not found, return empty Q
                if not match_property(property, override_property_values):
                    filters &= Q(pk__isnull=True)
            else:
                filters &= property.property_to_Q()
        return filters

    person_properties = [prop for prop in properties if prop.type == "person"]
    if len(person_properties) > 0:
        person_Q = Q()
        for property in person_properties:
            # short circuit query if key exists in override_property_values
            if property.key in override_property_values:
                # if match found, do nothing to Q
                # if not found, return empty Q
                if not match_property(property, override_property_values):
                    person_Q &= Q(pk__isnull=True)
            else:
                person_Q &= property.property_to_Q()

        filters &= Q(Exists(Person.objects.filter(person_Q, id=OuterRef("person_id")).only("pk")))

    event_properties = [prop for prop in properties if prop.type == "event"]
    if len(event_properties) > 0:
        raise ValueError("Event properties are no longer supported in properties_to_Q")

    # importing from .event and .cohort below to avoid importing from partially initialized modules

    element_properties = [prop for prop in properties if prop.type == "element"]
    if len(element_properties) > 0:
        raise ValueError("Element properties are no longer supported in properties_to_Q")

    cohort_properties = [prop for prop in properties if prop.type == "cohort"]
    if len(cohort_properties) > 0:
        from posthog.models.cohort import CohortPeople

        for item in cohort_properties:
            if item.key == "id":
                cohort_id = int(cast(Union[str, int], item.value))
                cohort: Cohort = Cohort.objects.get(pk=cohort_id)
                if cohort.is_static:
                    filters &= Q(
                        Exists(
                            CohortPeople.objects.filter(cohort_id=cohort.pk, person_id=OuterRef("person_id")).only("id")
                        )
                    )
                else:
                    filters &= Q(
                        Exists(
                            CohortPeople.objects.filter(
                                cohort_id=cohort.pk, person_id=OuterRef("person_id"), version=cohort.version
                            ).only("id")
                        )
                    )

    if len([prop for prop in properties if prop.type == "group"]):
        raise ValueError("Group properties are not supported for indirect filtering via postgres")

    return filters
