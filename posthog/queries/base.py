import datetime
import hashlib
import re
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    TypeVar,
    Union,
    cast,
)
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from dateutil import parser
from django.db.models import Exists, OuterRef, Q, Value
from rest_framework.exceptions import ValidationError

from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort, CohortPeople
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property import (
    Property,
    PropertyGroup,
)
from posthog.models.property.property import OperatorType, ValueT
from posthog.models.team import Team
from posthog.queries.util import convert_to_datetime_aware
from posthog.utils import get_compare_period_dates, is_valid_regex

FilterType = TypeVar("FilterType", Filter, PathFilter)


def determine_compared_filter(filter: FilterType) -> FilterType:
    if not filter.date_to or not filter.date_from:
        raise ValidationError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(
        filter.date_from,
        filter.date_to,
        filter.date_from_delta_mapping,
        filter.date_to_delta_mapping,
        filter.interval,
    )

    return filter.shallow_clone({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})


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

    if operator in ("exact", "is_not"):

        def compute_exact_match(value: ValueT, override_value: Any) -> bool:
            parsed_value = property._parse_value(value)
            if is_truthy_or_falsy_property_value(parsed_value):
                # Do boolean handling, such that passing in "true" or "True" or "false" or "False" as override value is equivalent
                truthy = parsed_value in (True, [True], "true", ["true"], "True", ["True"])
                return str(override_value).lower() == str(truthy).lower()

            if isinstance(value, list):
                return str(override_value).lower() in [str(val).lower() for val in value]
            return str(value).lower() == str(override_value).lower()

        if operator == "exact":
            return compute_exact_match(value, override_value)
        else:
            return not compute_exact_match(value, override_value)

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

    if operator in ("gt", "gte", "lt", "lte"):
        # :TRICKY: We adjust comparison based on the override value passed in,
        # to make sure we handle both numeric and string comparisons appropriately.
        def compare(lhs, rhs, operator):
            if operator == "gt":
                return lhs > rhs
            elif operator == "gte":
                return lhs >= rhs
            elif operator == "lt":
                return lhs < rhs
            elif operator == "lte":
                return lhs <= rhs
            else:
                raise ValueError(f"Invalid operator: {operator}")

        parsed_value = None
        try:
            parsed_value = float(value)  # type: ignore
        except Exception:
            pass

        if parsed_value is not None and override_value is not None:
            if isinstance(override_value, str):
                return compare(override_value, str(value), operator)
            else:
                return compare(override_value, parsed_value, operator)
        else:
            return compare(str(override_value), str(value), operator)

    if operator in ["is_date_before", "is_date_after", "is_relative_date_before", "is_relative_date_after"]:
        try:
            if operator in ["is_relative_date_before", "is_relative_date_after"]:
                parsed_date = relative_date_parse_for_feature_flag_matching(str(value))
            else:
                parsed_date = parser.parse(str(value))
                parsed_date = convert_to_datetime_aware(parsed_date)
        except Exception:
            return False

        if not parsed_date:
            return False

        if isinstance(override_value, datetime.datetime):
            override_date = convert_to_datetime_aware(override_value)
            if operator in ("is_date_before", "is_relative_date_before"):
                return override_date < parsed_date
            else:
                return override_date > parsed_date
        elif isinstance(override_value, datetime.date):
            if operator in ("is_date_before", "is_relative_date_before"):
                return override_value < parsed_date.date()
            else:
                return override_value > parsed_date.date()
        elif isinstance(override_value, str):
            try:
                override_date = parser.parse(override_value)
                override_date = convert_to_datetime_aware(override_date)
                if operator in ("is_date_before", "is_relative_date_before"):
                    return override_date < parsed_date
                else:
                    return override_date > parsed_date
            except Exception:
                return False

    return False


def empty_or_null_with_value_q(
    column: str,
    key: str,
    operator: Optional[OperatorType],
    value: ValueT,
    negated: bool = False,
) -> Q:
    if operator == "exact" or operator is None:
        value_as_given = Property._parse_value(value)
        value_as_coerced_to_number = Property._parse_value(value, convert_to_number=True)
        # TRICKY: Don't differentiate between 'true' and '"true"' when database matching (one is boolean, other is string)
        if is_truthy_or_falsy_property_value(value_as_given):
            truthy = value_as_given in (True, [True], "true", ["true"], "True", ["True"])
            target_filter = lookup_q(f"{column}__{key}", truthy) | lookup_q(f"{column}__{key}", str(truthy).lower())
        elif value_as_given == value_as_coerced_to_number:
            target_filter = lookup_q(f"{column}__{key}", value_as_given)
        else:
            target_filter = lookup_q(f"{column}__{key}", value_as_given) | lookup_q(
                f"{column}__{key}", value_as_coerced_to_number
            )
    else:
        parsed_value = None
        if operator in ("gt", "gte", "lt", "lte"):
            try:
                # try to parse even if arrays can't be parsed, the catch will handle it
                parsed_value = float(value)  # type: ignore
            except Exception:
                pass

        if parsed_value is not None:
            # When we can coerce given value to a number, check whether the value in DB is a number
            # and do a numeric comparison. Otherwise, do a string comparison.
            sanitized_key = sanitize_property_key(key)
            target_filter = Q(
                Q(**{f"{column}__{key}__{operator}": str(value), f"{column}_{sanitized_key}_type": Value("string")})
                | Q(**{f"{column}__{key}__{operator}": parsed_value, f"{column}_{sanitized_key}_type": Value("number")})
            )
        else:
            target_filter = Q(**{f"{column}__{key}__{operator}": value})

    query_filter = Q(target_filter & Q(**{f"{column}__has_key": key}) & ~Q(**{f"{column}__{key}": None}))

    if negated:
        return ~query_filter
    return query_filter


def lookup_q(key: str, value: Any) -> Q:
    # exact and is_not operators can pass lists as arguments. Handle those lookups!
    if isinstance(value, list):
        return Q(**{f"{key}__in": value})
    return Q(**{key: value})


def property_to_Q(
    property: Property,
    override_property_values: Dict[str, Any] = {},
    cohorts_cache: Optional[Dict[int, Cohort]] = None,
    using_database: str = "default",
) -> Q:
    if property.type not in ["person", "group", "cohort", "event"]:
        # We need to support event type for backwards compatibility, even though it's treated as a person property type
        raise ValueError(f"property_to_Q: type is not supported: {repr(property.type)}")

    value = property._parse_value(property.value)
    if property.type == "cohort":
        cohort_id = int(cast(Union[str, int], value))
        if cohorts_cache is not None:
            if cohorts_cache.get(cohort_id) is None:
                cohorts_cache[cohort_id] = Cohort.objects.using(using_database).get(pk=cohort_id)
            cohort = cohorts_cache[cohort_id]
        else:
            cohort = Cohort.objects.using(using_database).get(pk=cohort_id)

        if cohort.is_static:
            return Q(
                Exists(
                    CohortPeople.objects.using(using_database)
                    .filter(
                        cohort_id=cohort_id,
                        person_id=OuterRef("id"),
                        cohort__id=cohort_id,
                    )
                    .only("id")
                )
            )
        else:
            # :TRICKY: This has potential to create an infinite loop if the cohort is recursive.
            # But, this shouldn't happen because we check for cyclic cohorts on creation.
            return property_group_to_Q(
                cohort.properties,
                override_property_values,
                cohorts_cache,
                using_database,
            )

    # short circuit query if key exists in override_property_values
    if property.key in override_property_values and property.operator != "is_not_set":
        # if match found, add an explicit match-all Q object
        # if not found, return falsy Q
        if not match_property(property, override_property_values):
            return Q(pk__isnull=True)
        else:
            # TRICKY: We need to return an explicit match-all Q object, instead of an empty Q object,
            # because the empty Q object,  when OR'ed with other Q objects, results in removing the empty Q object.
            # This isn't what we want here, because this is an explicit true match, which when OR'ed with others,
            # should not be removed, and return True.
            # See https://code.djangoproject.com/ticket/32554 for gotcha explanation
            return Q(pk__isnull=False)

    # if no override matches, return a true Q object

    column = "group_properties" if property.type == "group" else "properties"

    if property.operator == "is_set":
        return Q(**{f"{column}__{property.key}__isnull": False})
    if property.operator == "is_not_set":
        return Q(**{f"{column}__{property.key}__isnull": True})
    if property.operator in ("regex", "not_regex") and not is_valid_regex(value):
        # Return no data for invalid regexes
        return Q(pk=-1)
    if isinstance(property.operator, str) and property.operator.startswith("not_"):
        return empty_or_null_with_value_q(
            column,
            property.key,
            cast(OperatorType, property.operator[4:]),
            value,
            negated=True,
        )

    if property.operator in ("is_date_after", "is_date_before", "is_relative_date_before", "is_relative_date_after"):
        effective_operator = "gt" if property.operator in ("is_date_after", "is_relative_date_after") else "lt"
        effective_value = value
        if property.operator in ("is_relative_date_before", "is_relative_date_after"):
            relative_date = relative_date_parse_for_feature_flag_matching(str(value))
            if relative_date:
                effective_value = relative_date.isoformat()
            else:
                # Return no data for invalid relative dates
                return Q(pk=-1)

        return Q(**{f"{column}__{property.key}__{effective_operator}": effective_value})

    if property.operator == "is_not":
        # is_not is inverse of exact
        return empty_or_null_with_value_q(column, property.key, "exact", value, negated=True)

    # NOTE: existence clause necessary when overall clause is negated
    return empty_or_null_with_value_q(column, property.key, property.operator, property.value)


def property_group_to_Q(
    property_group: PropertyGroup,
    override_property_values: Dict[str, Any] = {},
    cohorts_cache: Optional[Dict[int, Cohort]] = None,
    using_database: str = "default",
) -> Q:
    filters = Q()

    if not property_group or len(property_group.values) == 0:
        return filters

    if isinstance(property_group.values[0], PropertyGroup):
        for group in property_group.values:
            group_filter = property_group_to_Q(
                cast(PropertyGroup, group),
                override_property_values,
                cohorts_cache,
                using_database,
            )
            if property_group.type == PropertyOperatorType.OR:
                filters |= group_filter
            else:
                filters &= group_filter
    else:
        for property in property_group.values:
            property = cast(Property, property)
            property_filter = property_to_Q(property, override_property_values, cohorts_cache, using_database)
            if property_group.type == PropertyOperatorType.OR:
                if property.negation:
                    filters |= ~property_filter
                else:
                    filters |= property_filter
            else:
                if property.negation:
                    filters &= ~property_filter
                else:
                    filters &= property_filter

    return filters


def properties_to_Q(
    properties: List[Property],
    override_property_values: Dict[str, Any] = {},
    cohorts_cache: Optional[Dict[int, Cohort]] = None,
    using_database: str = "default",
) -> Q:
    """
    Converts a filter to Q, for use in Django ORM .filter()
    If you're filtering a Person/Group QuerySet, use is_direct_query to avoid doing an unnecessary nested loop
    """
    filters = Q()

    if len(properties) == 0:
        return filters

    return property_group_to_Q(
        PropertyGroup(type=PropertyOperatorType.AND, values=properties),
        override_property_values,
        cohorts_cache,
        using_database,
    )


def is_truthy_or_falsy_property_value(value: Any) -> bool:
    # Does not resolve 0 and 1 as true, but does resolve the strings as true
    return (
        value in ("true", ["true"], [True], [False], "false", ["false"], "True", ["True"], "False", ["False"])
        or value is True
        or value is False
    )


def relative_date_parse_for_feature_flag_matching(value: str) -> Optional[datetime.datetime]:
    regex = r"(?P<number>[0-9]+)(?P<interval>[a-z])"
    match = re.search(regex, value)
    parsed_dt = datetime.datetime.now(tz=ZoneInfo("UTC"))
    if match:
        number = int(match.group("number"))
        interval = match.group("interval")
        if interval == "h":
            parsed_dt = parsed_dt - relativedelta(hours=number)
        elif interval == "d":
            parsed_dt = parsed_dt - relativedelta(days=number)
        elif interval == "w":
            parsed_dt = parsed_dt - relativedelta(weeks=number)
        elif interval == "m":
            parsed_dt = parsed_dt - relativedelta(months=number)
        elif interval == "y":
            parsed_dt = parsed_dt - relativedelta(years=number)
        else:
            return None

        return parsed_dt
    else:
        return None


def sanitize_property_key(key: Any) -> str:
    string_key = str(key)
    # remove all but a-zA-Z0-9 characters from the key
    substitute = re.sub(r"[^a-zA-Z0-9]", "", string_key)

    # :TRICKY: We also want to prevent clashes between key1_ and key1, or key1 and key2 so we add
    #  a salt based on hash of the key
    # This is because we don't want to overwrite the value of key1 when we're trying to read key2
    hash_value = hashlib.sha1(string_key.encode("utf-8")).hexdigest()[:15]
    return f"{substitute}_{hash_value}"
