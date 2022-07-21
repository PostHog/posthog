import re
from typing import Any, Callable, Dict, List, Union, cast

from dateutil.relativedelta import relativedelta
from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import ValidationError

from posthog.models.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.utils import get_compare_period_dates, is_valid_regex


def determine_compared_filter(filter) -> Filter:
    if not filter.date_to or not filter.date_from:
        raise ValidationError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(filter.date_from, filter.date_to)

    date_from += relativedelta(days=1)
    return filter.with_data({"date_from": date_from.date().isoformat(), "date_to": date_to.date().isoformat()})


def convert_to_comparison(trend_entity: List[Dict[str, Any]], filter, label: str) -> List[Dict[str, Any]]:
    for entity in trend_entity:
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
    return trend_entity


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(filter, func: Callable, team: Team, **kwargs) -> List:
    entities_list = []
    trend_entity = func(filter=filter, team=team, **kwargs)
    if filter.compare:
        trend_entity = convert_to_comparison(trend_entity, filter, "current")
        entities_list.extend(trend_entity)

        compared_filter = determine_compared_filter(filter)
        compared_trend_entity = func(filter=compared_filter, team=team, **kwargs)

        compared_trend_entity = convert_to_comparison(compared_trend_entity, compared_filter, "previous",)
        entities_list.extend(compared_trend_entity)
    else:
        entities_list.extend(trend_entity)
    return entities_list


TIME_IN_SECONDS: Dict[str, Any] = {
    "hour": 3600,
    "day": 3600 * 24,
    "week": 3600 * 24 * 7,
    "month": 3600 * 24 * 30,  # TODO: Let's get rid of this lie! Months are not all 30 days long
}


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

    if operator == "regex":
        return is_valid_regex(str(value)) and re.compile(str(value)).search(str(override_value)) is not None

    if operator == "not_regex":
        return is_valid_regex(str(value)) and re.compile(str(value)).search(str(override_value)) is None

    if operator == "gt":
        return type(override_value) == type(value) and override_value > value

    if operator == "gte":
        return type(override_value) == type(value) and override_value >= value

    if operator == "lt":
        return type(override_value) == type(value) and override_value < value

    if operator == "lte":
        return type(override_value) == type(value) and override_value <= value

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

        filters &= Q(Exists(Person.objects.filter(person_Q, id=OuterRef("person_id"),).only("pk")))

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
                cohort = Cohort.objects.get(pk=cohort_id)
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
